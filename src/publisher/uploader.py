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
                # Clear and fill Title
                await title_box.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await title_box.fill(title)
                await page.wait_for_timeout(1000)
                await page.keyboard.press("Escape") # Dismiss autocomplete suggestions dropdown
                await page.wait_for_timeout(1000)
                # Click outside to blur title suggestions
                try:
                    await page.click("ytcp-uploads-dialog .title", timeout=2000)
                except Exception:
                    pass
                
                # Double check if title is filled, if not, fill it again
                current_title = await title_box.inner_text()
                if not current_title.strip() or current_title == "final_compilation.mp4":
                    logger.warning("Title was not set or got reset. Refilling...")
                    await title_box.click()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                    await title_box.fill(title)
                    await page.wait_for_timeout(1000)
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(1000)
                    try:
                        await page.click("ytcp-uploads-dialog .title", timeout=2000)
                    except Exception:
                        pass
                
                logger.info(f"Filled Title: {title}")

                # Fill Description
                desc_box = page.locator("#description-textarea #textbox")
                try:
                    await desc_box.first.wait_for(state="visible", timeout=10000)
                    # Directly evaluate text input using JS or force click
                    await page.evaluate("""(text) => {
                        const box = document.querySelector('#description-textarea #textbox');
                        if (box) {
                            box.focus();
                            box.innerText = text;
                            box.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    }""", description)
                except Exception as desc_err:
                    logger.warning(f"Direct description fill failed: {desc_err}. Trying standard click and fill...")
                    try:
                        await desc_box.first.click(force=True, timeout=5000)
                        await page.keyboard.press("Control+A")
                        await page.keyboard.press("Backspace")
                        await desc_box.first.fill(description)
                    except Exception as inner_err:
                        logger.error(f"Failed to fill description: {inner_err}")
                logger.info("Filled Description.")

                # Dismiss autocomplete overlay by pressing Escape
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(1000)
                
                # Mark as 'not made for kids' (required step)
                logger.info("Selecting 'Not made for kids'...")
                try:
                    await page.evaluate("""() => {
                        const radios = Array.from(document.querySelectorAll('tp-yt-paper-radio-button, ytcp-radio-button, paper-radio-button, [role="radio"]'));
                        // Find the one containing "No" or "否"
                        const kidsNo = radios.find(r => {
                            const text = r.textContent || '';
                            return text.includes('No') || text.includes('否');
                        });
                        if (kidsNo) {
                            kidsNo.scrollIntoView({ block: 'center' });
                            kidsNo.click();
                        } else {
                            // Fallback to name selector
                            const nameRadio = document.querySelector('[name="VIDEO_MADE_FOR_KIDS_NOT_MADE_FOR_KIDS"]');
                            if (nameRadio) nameRadio.click();
                        }
                    }""")
                    await page.wait_for_timeout(2000)
                except Exception as kids_err:
                    logger.warning(f"JS kids selection failed: {kids_err}")
                
                # Click Next buttons through the wizard steps
                # There are 3-4 "Next" buttons depending on the channel status
                logger.info("Navigating through wizard steps...")
                for step in range(3):
                    try:
                        await page.evaluate("""() => {
                            const nextBtn = document.querySelector('#next-button') || document.querySelector('ytcp-button[id="next-button"]');
                            if (nextBtn) {
                                nextBtn.scrollIntoView({ block: 'center' });
                                nextBtn.click();
                            }
                        }""")
                        logger.info(f"Clicked Next button (Step {step + 1})")
                        await page.wait_for_timeout(2500)
                    except Exception as step_err:
                        logger.warning(f"Failed to click Next button on step {step+1}: {step_err}")

                # Visibility step: set to public
                logger.info("Setting visibility to Public...")
                try:
                    await page.evaluate("""() => {
                        const radios = Array.from(document.querySelectorAll('tp-yt-paper-radio-button, ytcp-radio-button, paper-radio-button, [role="radio"]'));
                        const publicRadio = radios.find(r => {
                            const text = r.textContent || '';
                            return text.includes('Public') || text.includes('公開') || text.includes('公开');
                        });
                        if (publicRadio) {
                            publicRadio.scrollIntoView({ block: 'center' });
                            publicRadio.click();
                        }
                    }""")
                    await page.wait_for_timeout(2000)
                except Exception as vis_err:
                    logger.warning(f"Failed to set visibility: {vis_err}")

                # Click Publish button (which has id='done-button' or 'publish-button')
                logger.info("Publishing video...")
                try:
                    await page.evaluate("""() => {
                        const doneBtn = document.querySelector('#done-button') || document.querySelector('#publish-button') || document.querySelector('ytcp-button[id="done-button"]');
                        if (doneBtn) {
                            doneBtn.scrollIntoView({ block: 'center' });
                            doneBtn.click();
                        } else {
                            // Find any button with text "Publish", "Done", "發布", "完成"
                            const btns = Array.from(document.querySelectorAll('ytcp-button, button'));
                            const pubBtn = btns.find(b => {
                                const text = b.textContent || '';
                                return text.includes('Publish') || text.includes('Done') || text.includes('發布') || text.includes('完成') || text.includes('公开发布');
                            });
                            if (pubBtn) pubBtn.click();
                        }
                    }""")
                    logger.info("Clicked Publish button!")
                    await page.wait_for_timeout(5000)
                except Exception as pub_err:
                    logger.error(f"Failed to click publish button: {pub_err}")
                    raise pub_err

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
