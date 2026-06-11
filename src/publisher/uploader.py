import os
import logging
import json
import asyncio
import re
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class AutoPublisher:
    def __init__(self, platform="youtube", cookie_dir="workspace/cookies", headless=False):
        self.platform = platform
        self.cookie_dir = cookie_dir
        os.makedirs(self.cookie_dir, exist_ok=True)
        self.cookie_path = os.path.join(self.cookie_dir, f"{self.platform}.json")
        self.headless = headless

    async def _init_browser(self, playwright):
        """
        Launches the browser with loaded cookies if they exist.
        """
        browser = await playwright.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
        
        context_args = {}
        if os.path.exists(self.cookie_path):
            logger.info(f"Loading existing cookies for {self.platform} from {self.cookie_path}")
            with open(self.cookie_path, 'r') as f:
                cookies = json.load(f)
            context_args["storage_state"] = cookies
            
        context = await browser.new_context(**context_args)
        return browser, context

    async def save_login_session(self):
        """
        Opens a browser in GUI mode to let the user log in manually.
        Once the user is logged in (monitored by checking dashboard URL), saves the cookies.
        """
        logger.info(f"Starting login session for {self.platform}...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            if self.platform == "youtube":
                await page.goto("https://studio.youtube.com")
                print("=========================================================")
                print(" Please log in to your YouTube Studio account in the GUI browser.")
                print(" The script will automatically detect once you are logged in.")
                print("=========================================================")
                
                # Wait for the user to reach the studio dashboard
                await page.wait_for_url("**/channel/**", timeout=0)
            elif self.platform == "tiktok":
                await page.goto("https://www.tiktok.com/login")
                print("=========================================================")
                print(" Please log in to your TikTok account in the GUI browser.")
                print("=========================================================")
                await page.wait_for_url("**/creator-center**", timeout=0)
                
            # Save storage state (cookies & localStorage)
            state = await context.storage_state()
            with open(self.cookie_path, 'w') as f:
                json.dump(state, f)
            logger.info(f"Saved login session cookies to {self.cookie_path}")
            await browser.close()

    async def publish_youtube_shorts(self, video_path, title, description="#shorts"):
        """
        Uploads and publishes a video to YouTube Shorts using Playwright.
        """
        logger.info(f"Starting YouTube upload for video: {video_path}")
        if not os.path.exists(self.cookie_path):
            logger.error(f"No cookies found for YouTube. Run save_login_session() first.")
            raise FileNotFoundError("Authentication cookies not found. Please log in first.")

        async with async_playwright() as p:
            browser, context = await self._init_browser(p)
            page = await context.new_page()
            
            try:
                await page.goto("https://studio.youtube.com")
                # Check if we are logged in by searching for the upload button
                await page.wait_for_selector("#upload-icon", timeout=15000)
                logger.info("Successfully authenticated via cookies.")
                
                # Click upload button
                await page.click("#upload-icon")
                
                # Select file input
                file_input = page.locator("input[type=file]")
                await file_input.set_input_files(video_path)
                logger.info("Selected video file for upload. Waiting for upload details form...")

                # Wait for the title textbox to appear
                # On YouTube Studio, the details input has id='textbox' or class='textbox'
                title_box = page.locator("#title-textarea #textbox")
                await title_box.wait_for(timeout=30000)
                
                # Wait 5 seconds to let the YouTube upload dialog stabilize and auto-fill the default filename
                logger.info("Waiting for upload form to stabilize...")
                await page.wait_for_timeout(5000)
                
                # Clear and fill Title
                await title_box.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await title_box.fill(title)
                await page.wait_for_timeout(1000)
                await page.keyboard.press("Escape") # Dismiss autocomplete suggestions dropdown
                await page.wait_for_timeout(1000)
                
                # Double check if title is filled, if not, fill it again
                current_title = await title_box.inner_text()
                if not current_title.strip() or current_title == "final_compilation.mp4":
                    logger.warning("Title was not set or got reset. Refilling...")
                    await title_box.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await title_box.fill(title)
                    await page.wait_for_timeout(1000)
                    await page.keyboard.press("Escape") # Dismiss autocomplete suggestions dropdown
                    await page.wait_for_timeout(1000)
                
                logger.info(f"Filled Title: {title}")

                # Fill Description
                desc_box = page.locator("#description-textarea #textbox")
                try:
                    await desc_box.click(timeout=5000)
                except Exception as click_err:
                    logger.warning(f"Normal click on description box failed: {click_err}. Trying force click...")
                    await desc_box.click(force=True)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await desc_box.fill(description)
                logger.info("Filled Description.")

                # Dismiss autocomplete overlay by shifting focus to the title container
                try:
                    await page.locator("#title-textarea").first.click()
                    await page.wait_for_timeout(1000)
                except Exception as focus_err:
                    logger.warning(f"Could not shift focus: {focus_err}")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(1000)
                
                try:
                    await page.evaluate("document.querySelector('#scrollable-content').scrollTop = 1000")
                    await page.wait_for_timeout(1000)
                except Exception as scroll_err:
                    logger.warning(f"Could not scroll container: {scroll_err}")

                # Mark as 'not made for kids' (required step)
                kids_radio = page.locator("tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MADE_FOR_KIDS'], ytcp-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MADE_FOR_KIDS']")
                if await kids_radio.count() == 0:
                    # Using unicode escapes to prevent encoding corruption on Windows/CP950
                    # "\u5426\uff0c\u9019" matches "否，這"
                    kids_radio = page.locator("tp-yt-paper-radio-button, ytcp-radio-button, paper-radio-button, .radio-button").filter(
                        has_text=re.compile("(No, it's not made for kids|\u5426\uff0c\u9019|No, it is not made for kids)", re.IGNORECASE)
                    )
                
                await kids_radio.scroll_into_view_if_needed()
                await kids_radio.click()
                
                # Click Next buttons through the wizard steps
                # There are 3-4 "Next" buttons depending on the channel status
                next_btn_selector = "#next-button"
                for step in range(3):
                    next_btn = page.locator(next_btn_selector)
                    await next_btn.wait_for(state="visible")
                    await next_btn.click()
                    logger.info(f"Clicked Next button (Step {step + 1})")
                    await page.wait_for_timeout(2000)

                # Visibility step: set to public
                logger.info("Setting visibility to Public...")
                public_radio = page.locator("tp-yt-paper-radio-button[name='PUBLIC'], ytcp-radio-button[name='PUBLIC']")
                if await public_radio.count() == 0:
                    # "\u516c\u958b" matches "公開"
                    public_radio = page.locator("tp-yt-paper-radio-button, ytcp-radio-button, paper-radio-button").filter(
                        has_text=re.compile("(Public|\u516c\u958b)", re.IGNORECASE)
                    )
                await public_radio.scroll_into_view_if_needed()
                await public_radio.click()

                # Click Publish button (which has id='done-button' or 'publish-button')
                publish_btn = page.locator("#done-button, #publish-button")
                if await publish_btn.count() == 0:
                    # Unicode escapes for "公開發布", "發布", "完成"
                    publish_btn = page.locator("ytcp-button").filter(
                        has_text=re.compile("(Publish|Done|\u516c\u958b\u767c\u5e03|\u767c\u5e03|\u5b8c\u6210)", re.IGNORECASE)
                    )
                await publish_btn.wait_for(state="visible")
                await publish_btn.click()
                logger.info("Clicked Publish button!")

                # Wait for completion dialog
                await page.wait_for_timeout(5000)
                logger.info("Upload and publish completed successfully.")
            except Exception as e:
                logger.error(f"Failed to upload video: {e}")
                # Save screenshot of error for debugging
                debug_screenshot = os.path.join(self.cookie_dir, "error_screenshot.png")
                await page.screenshot(path=debug_screenshot)
                logger.info(f"Saved error screenshot to: {debug_screenshot}")
                raise e
            finally:
                # Save state in case cookies updated
                state = await context.storage_state()
                with open(self.cookie_path, 'w') as f:
                    json.dump(state, f)
                await browser.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    publisher = AutoPublisher(headless=False)
    
    # Test session saving
    # asyncio.run(publisher.save_login_session())
    
    # Test uploading
    # asyncio.run(publisher.publish_youtube_shorts("workspace/output/result_shorts.mp4", "Automated Shorts Title", "#shorts #tech"))
