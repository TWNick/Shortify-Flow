import os
import json
import logging
import asyncio
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class FlowVideoGenerator:
    def __init__(self, cookie_dir="workspace/cookies", headless=True):
        self.cookie_dir = cookie_dir
        os.makedirs(self.cookie_dir, exist_ok=True)
        self.cookie_path = os.path.join(self.cookie_dir, "flow.json")
        self.headless = headless

    async def save_login_session(self):
        """
        Opens a browser in GUI mode to let the user log in to Google Flow.
        Automatically monitors the page. Once the login is successful and the user 
        enters the Flow workspace, it saves the storage state and automatically 
        closes the browser without needing terminal interaction.
        """
        logger.info("Starting login session for Google Flow...")
        
        storage_state = None
        gemini_cookie = os.path.join(self.cookie_dir, "gemini.json")
        flow_cookie = os.path.join(self.cookie_dir, "flow.json")
        
        if os.path.exists(flow_cookie):
            logger.info("Using existing flow.json as starting state...")
            storage_state = flow_cookie
        elif os.path.exists(gemini_cookie):
            logger.info("Using gemini.json as starting state to bypass initial Google login...")
            storage_state = gemini_cookie
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
            )
            
            if storage_state:
                context = await browser.new_context(
                    storage_state=storage_state,
                    no_viewport=True
                )
            else:
                context = await browser.new_context(no_viewport=True)
                
            page = await context.new_page()
            
            logger.info("Navigating to https://labs.google/fx/tools/flow...")
            await page.goto("https://labs.google/fx/tools/flow")
            
            print("=========================================================")
            print(" [自動偵測登入] 瀏覽器已在您的桌面開啟。")
            print(" 請在瀏覽器中登入您的 Google 帳號。")
            print(" 一旦您成功進入 Google Flow 編輯工作區，本程式將會：")
            print(" 1. 自動儲存 Cookie。")
            print(" 2. 自動關閉瀏覽器視窗。")
            print(" 3. 繼續背景工作。")
            print("=========================================================")
            
            max_wait_seconds = 300  # 5 minutes
            check_interval = 1.5
            elapsed = 0
            login_success = False
            
            while elapsed < max_wait_seconds:
                try:
                    # Check if all pages are closed (meaning user closed the browser)
                    all_closed = True
                    for p_item in context.pages:
                        if not p_item.is_closed():
                            all_closed = False
                            break
                    if all_closed:
                        logger.warning("All browser windows were closed by the user.")
                        break
                        
                    # Target the active/latest page for clicking buttons
                    active_page = context.pages[-1] if context.pages else page
                    if active_page.is_closed():
                        active_page = page
                        
                    current_url = active_page.url
                    if int(elapsed) % 6 == 0:
                        logger.info(f"Monitoring... Active URL: {current_url} (Total open tabs: {len(context.pages)})")
                        
                    if int(elapsed) % 15 == 0:
                        try:
                            btn_elms = active_page.locator("button, a")
                            btn_count = await btn_elms.count()
                            btn_texts = []
                            for idx in range(min(15, btn_count)):
                                txt = await btn_elms.nth(idx).inner_text()
                                href = await btn_elms.nth(idx).get_attribute("href")
                                btn_texts.append(f"{txt[:20]}(href={href})")
                            logger.info(f"Debug elements on page: {btn_texts}")
                        except Exception as dbg_err:
                            logger.debug(f"Debug printer error: {dbg_err}")
                        
                    # Use precise terms to avoid hitting non-clickable/anchor links like #flow-sessions
                    create_btn = active_page.locator("button:has-text('Create with Google Flow'), a:has-text('Create with Google Flow'), span:has-text('Create with Google Flow'), button:has-text('Try the Google Flow'), a:has-text('Try the Google Flow'), span:has-text('Try the Google Flow'), button:has-text('Try in Google Flow'), a:has-text('Try in Google Flow'), span:has-text('Try in Google Flow')")
                    
                    if await create_btn.count() > 0:
                        logger.info("Found 'Create with Google Flow' button. Clicking it to proceed...")
                        await create_btn.first.click()
                        await asyncio.sleep(3)
                        continue
                        
                    # Scan all pages to detect workspace entry
                    for p_item in context.pages:
                        if p_item.is_closed():
                            continue
                        p_url = p_item.url
                        if "tools/flow" in p_url and not ("signin" in p_url or "accounts.google.com" in p_url):
                            textareas = p_item.locator("textarea, [contenteditable='true']")
                            ta_count = await textareas.count()
                            
                            # Also check for project creation button (indicating we are in the dashboard/project list)
                            add_project_btn = p_item.locator("button:has-text('add_2'), button:has-text('新建'), button:has-text('New Project')")
                            add_count = await add_project_btn.count()
                            
                            if ta_count > 0 or add_count > 0 or "workspace" in p_url or "projects" in p_url or "project" in p_url:
                                logger.info(f"Successfully detected Google Flow workspace or project list elements on tab: {p_url}!")
                                login_success = True
                                break
                                
                    if login_success:
                        break
                            
                except Exception as monitor_err:
                    logger.debug(f"Monitoring tick error: {monitor_err}")
                    
                await asyncio.sleep(check_interval)
                elapsed += check_interval
                
            if login_success:
                logger.info("Saving session cookies...")
                await asyncio.sleep(3)
                state = await context.storage_state()
                with open(self.cookie_path, 'w', encoding='utf-8') as f:
                    json.dump(state, f)
                logger.info(f"Saved Google Flow login session cookies to {self.cookie_path}")
            else:
                logger.warning("Could not verify successful login within the timeout period or browser was closed.")
                
            await browser.close()

    async def explore_flow(self):
        """
        Explores the flow.google workspace by clicking into it and listing DOM elements.
        """
        logger.info("Starting Google Flow workspace exploration...")
        
        cookie_file = self.cookie_path
        if not os.path.exists(cookie_file):
            gemini_cookie = os.path.join(self.cookie_dir, "gemini.json")
            if os.path.exists(gemini_cookie):
                logger.info("flow.json not found. Attempting fallback to gemini.json cookies...")
                cookie_file = gemini_cookie
            else:
                raise FileNotFoundError("Neither flow.json nor gemini.json was found.")
                
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(storage_state=cookie_file)
            page = await context.new_page()
            
            try:
                await page.goto("https://labs.google/fx/tools/flow")
                logger.info("Page loaded. Waiting 5 seconds...")
                await asyncio.sleep(5)
                
                logger.info(f"Page Title: {await page.title()}")
                logger.info(f"Current URL: {page.url}")
                
                # Click 'Create with Google Flow' button
                create_btn = page.locator("button:has-text('Create with Google Flow'), a:has-text('Create with Google Flow'), span:has-text('Create with Google Flow')")
                try_btn = page.locator("button:has-text('Try in Google Flow'), a:has-text('Try in Google Flow'), span:has-text('Try in Google Flow')")
                
                target_btn = None
                if await create_btn.count() > 0:
                    target_btn = create_btn.first
                elif await try_btn.count() > 0:
                    target_btn = try_btn.first
                    
                if target_btn:
                    logger.info("Clicking to enter workspace...")
                    try:
                        async with context.expect_page(timeout=10000) as new_page_info:
                            await target_btn.click()
                        page = await new_page_info.value
                        logger.info("Successfully switched page reference to the new workspace tab.")
                    except Exception as tab_err:
                        logger.warning(f"Did not detect new tab opening via popup event: {tab_err}. Checking if page redirected or checking other tabs...")
                        await page.wait_for_timeout(5000)
                        if len(context.pages) > 1:
                            page = context.pages[-1]
                            await page.bring_to_front()
                            logger.info("Switched to the last opened page/tab.")
                            
                logger.info("Waiting 15 seconds for workspace redirect and loading...")
                await asyncio.sleep(15)
                
                logger.info(f"New Page Title: {await page.title()}")
                logger.info(f"New Current URL: {page.url}")
                
                # Save new state to flow.json after redirection
                state = await context.storage_state()
                with open(self.cookie_path, 'w', encoding='utf-8') as f:
                    json.dump(state, f)
                logger.info(f"Saved authenticated state to {self.cookie_path}")
                
                # Take screenshot of the workspace
                screenshot_path = os.path.join(self.cookie_dir, "flow_workspace.png")
                await page.screenshot(path=screenshot_path)
                logger.info(f"Saved workspace screenshot to {screenshot_path}")
                
                # List textareas and inputs again in workspace
                textareas = page.locator("textarea, [contenteditable='true']")
                ta_count = await textareas.count()
                logger.info(f"Workspace textareas/editors count: {ta_count}")
                for i in range(ta_count):
                    ta = textareas.nth(i)
                    logger.info(f"Editor {i}: placeholder='{await ta.get_attribute('placeholder')}', text='{await ta.inner_text()}', id='{await ta.get_attribute('id')}', class='{await ta.get_attribute('class')}'")
                    
                buttons = page.locator("button")
                btn_count = await buttons.count()
                logger.info(f"Workspace buttons count: {btn_count}")
                for i in range(min(40, btn_count)):
                    btn = buttons.nth(i)
                    logger.info(f"Workspace Button {i}: text='{await btn.inner_text()}', id='{await btn.get_attribute('id')}', class='{await btn.get_attribute('class')}'")
                    
            except Exception as e:
                logger.error(f"Error exploring flow.google: {e}")
            finally:
                await browser.close()

    async def generate_scene_video(self, prompt, duration, output_path, retry_on_signin=True):
        """
        Generates a video clip using Google Flow.
        Creates a new project, inputs the prompt, waits for generation, and downloads the video.
        """
        logger.info(f"Generating video clip via Google Flow for prompt: '{prompt}' (Target: {duration:.2f}s)")
        if not os.path.exists(self.cookie_path):
            logger.warning("flow.json cookies not found. Triggering interactive login session...")
            await self.save_login_session()
            if not os.path.exists(self.cookie_path):
                raise FileNotFoundError("flow.json cookies not found even after login session.")
            
        # Determine initial storage state (leveraging active Google SSO from gemini.json)
        storage_state = self.cookie_path
        gemini_cookie = os.path.join(self.cookie_dir, "gemini.json")
        if os.path.exists(self.cookie_path):
            logger.info("Using existing flow.json cookies...")
            storage_state = self.cookie_path
        elif os.path.exists(gemini_cookie):
            logger.info("Using gemini.json cookies to leverage active Google SSO session...")
            storage_state = gemini_cookie
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(storage_state=storage_state)
            page = await context.new_page()
            
            try:
                # 1. Open Google Flow studio dashboard
                logger.info("Opening Google Flow studio dashboard...")
                await page.goto("https://labs.google/fx/zh/tools/flow")
                await page.wait_for_timeout(5000)
                
                # Check for signin redirection immediately
                if "signin" in page.url or "accounts.google.com" in page.url or "error=Callback" in page.url:
                    if retry_on_signin:
                        logger.warning(f"Google Flow session expired or unauthorized (Redirected to: {page.url}). Triggering interactive login session...")
                        await browser.close()
                        if os.path.exists(self.cookie_path):
                            try:
                                logger.info(f"Removing expired cookie file: {self.cookie_path}")
                                os.remove(self.cookie_path)
                            except Exception as rm_err:
                                logger.warning(f"Failed to remove expired cookie file: {rm_err}")
                        await self.save_login_session()
                        return await self.generate_scene_video(prompt, duration, output_path, retry_on_signin=False)
                    else:
                        raise RuntimeError(f"Failed to authenticate even after triggering login session. Current URL: {page.url}")
                
                # If we are on the landing page, click "Create with Google Flow" to enter the workspace
                create_btn = page.locator("button:has-text('Create with Google Flow'), a:has-text('Create with Google Flow'), span:has-text('Create with Google Flow'), button:has-text('Try the Google Flow'), a:has-text('Try the Google Flow'), span:has-text('Try the Google Flow'), button:has-text('Try in Google Flow'), a:has-text('Try in Google Flow'), span:has-text('Try in Google Flow')")
                if await create_btn.count() > 0:
                    logger.info("Found 'Create with Google Flow' button on landing page. Clicking to enter workspace...")
                    try:
                        async with context.expect_page(timeout=10000) as new_page_info:
                            await create_btn.first.click()
                        page = await new_page_info.value
                        logger.info("Successfully switched page reference to the new workspace tab.")
                    except Exception as tab_err:
                        logger.warning(f"Did not detect new tab opening via popup event: {tab_err}. Checking if page redirected or checking other tabs...")
                        await page.wait_for_timeout(5000)
                        if len(context.pages) > 1:
                            page = context.pages[-1]
                            await page.bring_to_front()
                            logger.info("Switched to the last opened page/tab.")
                    await page.wait_for_timeout(10000)
                    
                    # Check for signin redirection again in the new tab
                    if "signin" in page.url or "accounts.google.com" in page.url or "error=Callback" in page.url:
                        if retry_on_signin:
                            logger.warning(f"Google Flow session expired or unauthorized in workspace tab (Redirected to: {page.url}). Triggering interactive login session...")
                            await browser.close()
                            if os.path.exists(self.cookie_path):
                                try:
                                    logger.info(f"Removing expired cookie file: {self.cookie_path}")
                                    os.remove(self.cookie_path)
                                except Exception as rm_err:
                                    logger.warning(f"Failed to remove expired cookie file: {rm_err}")
                            await self.save_login_session()
                            return await self.generate_scene_video(prompt, duration, output_path, retry_on_signin=False)
                        else:
                            raise RuntimeError(f"Failed to authenticate in workspace tab even after triggering login session. Current URL: {page.url}")
                
                # Dismiss any changelog iframes or welcome overlay popups to prevent blocking pointer events
                try:
                    await page.evaluate("""() => {
                        // Find any iframe that might be a changelog or gallery popup
                        const iframes = document.querySelectorAll('iframe');
                        iframes.forEach(iframe => {
                            // Traverse up to find the wrapping modal container
                            let parent = iframe.parentElement;
                            let modalContainer = iframe;
                            while (parent && parent !== document.body) {
                                const style = window.getComputedStyle(parent);
                                if (style.position === 'fixed' || style.position === 'absolute') {
                                    modalContainer = parent;
                                }
                                parent = parent.parentElement;
                            }
                            modalContainer.remove();
                        });
                        
                        // Also remove any remaining backdrops/overlays (elements with fixed/absolute positioning that cover the viewport)
                        document.querySelectorAll('*').forEach(el => {
                            if (el === document.body || el === document.documentElement) return;
                            try {
                                const style = window.getComputedStyle(el);
                                if (style.position === 'fixed' && parseInt(style.zIndex) > 5) {
                                    if (el.offsetWidth > window.innerWidth * 0.8 && el.offsetHeight > window.innerHeight * 0.8) {
                                        el.remove();
                                    }
                                }
                            } catch(e) {}
                        });
                    }""")
                    logger.info("Checked and removed any blocking iframe/modal overlays on dashboard.")
                except Exception as eval_err:
                    logger.warning(f"Failed to clear modal overlays: {eval_err}")
                
                # 2. Click 'add_2' or '新建' or 'New Project' to create a new project
                add_btn = page.locator("button:has-text('add_2'), button:has-text('新建'), button:has-text('New Project')")
                if await add_btn.count() > 0:
                    logger.info("Creating new project...")
                    await add_btn.first.click()
                    
                    # Wait for redirect and editor element to be loaded
                    logger.info("Waiting for workspace page and editor to load...")
                    try:
                        # Wait until URL contains /project/
                        await page.wait_for_url(lambda url: "/project/" in url, timeout=20000)
                        logger.info(f"Redirected to project URL: {page.url}")
                    except Exception as url_err:
                        logger.warning(f"Timeout waiting for URL redirect to contain '/project/': {url_err}. Current URL: {page.url}")
                    
                    try:
                        # Wait for the main editor text area to be visible
                        await page.wait_for_selector("[contenteditable='true'], textarea", state="visible", timeout=25000)
                        logger.info("Workspace editor element loaded successfully.")
                    except Exception as sel_err:
                        logger.warning(f"Timeout waiting for editor element: {sel_err}. Proceeding anyway...")
                        await page.wait_for_timeout(5000)
                    
                    # Update flow.json since we successfully authenticated and entered project
                    try:
                        state = await context.storage_state()
                        with open(self.cookie_path, 'w', encoding='utf-8') as f:
                            json.dump(state, f)
                        logger.info(f"Updated Google Flow session cookies at {self.cookie_path}")
                    except Exception as save_err:
                        logger.warning(f"Could not update flow.json: {save_err}")
                else:
                    if retry_on_signin:
                        logger.warning(f"Could not find project creation button on page {page.url}. Google Flow session might be invalid. Triggering interactive login session...")
                        await browser.close()
                        if os.path.exists(self.cookie_path):
                            try:
                                logger.info(f"Removing expired cookie file: {self.cookie_path}")
                                os.remove(self.cookie_path)
                            except Exception as rm_err:
                                logger.warning(f"Failed to remove expired cookie file: {rm_err}")
                        await self.save_login_session()
                        return await self.generate_scene_video(prompt, duration, output_path, retry_on_signin=False)
                    else:
                        raise RuntimeError(f"Could not find project creation button ('add_2', '新建', 'New Project') on page {page.url}.")
                
                # Capture initial resource links
                links_before = set()
                links = page.locator("a")
                link_count = await links.count()
                for i in range(link_count):
                    href = await links.nth(i).get_attribute("href")
                    if href and "/edit/" in href:
                        links_before.add(href)
                logger.info(f"Existing resource links: {links_before}")
                
                # 3. Dismiss modal overlays
                logger.info("Dismissing any modal overlays...")
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(1000)
                
                close_buttons = page.locator("button:has-text('close'), button:has-text('關閉'), button:has-text('关闭'), button:has-text('確定'), button:has-text('确定')")
                if await close_buttons.count() > 0:
                    try:
                        await close_buttons.first.click(timeout=2000)
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                
                # 4. Configure to Video mode and 9:16 aspect ratio
                settings_btn = page.locator("button:has-text('tune 设置'), button:has(i:has-text('tune')), button:has(i:has-text('crop_')), button:has-text('Nano Banana')").first
                
                # Wait for settings button to be visible
                try:
                    await settings_btn.wait_for(state="visible", timeout=15000)
                except Exception as e:
                    logger.warning(f"Settings button not visible yet: {e}")
                    
                if await settings_btn.count() > 0:
                    logger.info("Opening model settings dropdown...")
                    await settings_btn.click()
                    await page.wait_for_timeout(2000)
                    
                    video_tab = page.locator("button[role='tab']:has-text('视频'), button[id*='trigger-VIDEO']")
                    if await video_tab.count() > 0:
                        logger.info("Selecting '视频' (Video) mode...")
                        await video_tab.first.click()
                        await page.wait_for_timeout(1500)
                    else:
                        logger.info("Video tab option not found (using default video model settings).")
                        
                    # Select "永不" (Never ask/AUTO_APPROVE) point confirmation setting
                    auto_approve_btn = page.locator("button[role='radio']:has-text('永不'), button[value='AUTO_APPROVE']")
                    if await auto_approve_btn.count() > 0:
                        logger.info("Selecting Auto Approve points settings...")
                        await auto_approve_btn.first.click()
                        await page.wait_for_timeout(1000)
                        
                    ratio_tab = page.locator("button[role='tab']:has-text('9:16'), button[id*='trigger-PORTRAIT']")
                    if await ratio_tab.count() > 0:
                        logger.info("Selecting '9:16' aspect ratio...")
                        await ratio_tab.first.click()
                        await page.wait_for_timeout(1500)
                    else:
                        logger.warning("9:16 aspect ratio option not found.")
                        
                    # Click '保存' (Save) button to apply settings in new UI
                    save_btn = page.locator("button:has-text('保存'), button:has-text('Save')")
                    if await save_btn.count() > 0:
                        logger.info("Clicking Save settings button...")
                        await save_btn.first.click()
                        await page.wait_for_timeout(1500)
                    else:
                        # Close settings menu via Escape if no Save button exists
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(1000)
                    
                    logger.info(f"Successfully configured Flow settings: {await settings_btn.inner_text()}")
                else:
                    logger.warning("Could not find model settings button.")
                
                # 5. Input prompt
                # Cancel any default templates or welcome runs first by clicking the stop button if visible
                stop_btn = page.locator("button:has(i:has-text('stop')), button:has(i:has-text('stop_circle'))")
                if await stop_btn.count() > 0 and await stop_btn.first.is_visible():
                    logger.info("Chat assistant is busy generating default template. Clicking stop button to cancel...")
                    try:
                        await stop_btn.first.click(timeout=3000)
                        await page.wait_for_timeout(2000)
                    except Exception as stop_err:
                        logger.warning(f"Could not click stop button: {stop_err}")
                
                editors = page.locator("[contenteditable='true']")
                if await editors.count() > 0:
                    logger.info("Inputting generation prompt...")
                    prompt_editor = editors.first
                    await prompt_editor.click(force=True)
                    await page.wait_for_timeout(1000)
                    
                    # Focus and clear text using standard keyboard presses
                    await prompt_editor.focus()
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Delete")
                    await page.wait_for_timeout(500)
                    
                    # Type prompt text using Playwright keyboard API to trigger Slate.js state synchronization
                    await page.keyboard.type(prompt)
                    await page.wait_for_timeout(2000)
                else:
                    raise RuntimeError("Could not find prompt editor textarea.")
                
                # 6. Click generate button (arrow_forward)
                logger.info("Locating and submitting video generation task...")
                gen_btn = page.locator("button:has(i:has-text('arrow_forward')), button:has-text('arrow_forward')").first
                try:
                    await gen_btn.wait_for(state="visible", timeout=15000)
                except Exception as wait_err:
                    logger.warning(f"Timeout waiting for generate button visibility: {wait_err}")
                
                click_res = {"success": False, "error": None}
                if await gen_btn.count() > 0:
                    is_disabled = await gen_btn.get_attribute("aria-disabled") == "true" or await gen_btn.evaluate("el => el.disabled")
                    if not is_disabled:
                        try:
                            logger.info("Clicking generate button via Playwright...")
                            await gen_btn.click(timeout=5000)
                            click_res["success"] = True
                        except Exception as click_err:
                            click_res["error"] = f"Click failed: {click_err}"
                    else:
                        click_res["error"] = "Generate button is disabled"
                else:
                    click_res["error"] = "Generate button not found on page"
                
                if not click_res.get("success"):
                    # Check if there is a warning/alert element in the prompt container area
                    alert_locator = page.locator("div:has(img[src*='flow_alert_sphere.svg']), div:has(i:has-text('info')), [class*='alert'], [class*='hicSpj']").last
                    if await alert_locator.count() > 0:
                        logger.warning("Alert sphere or warning icon detected instead of the Generate button. Attempting to extract error message...")
                        try:
                            # 1. Hover first to trigger tooltip
                            await alert_locator.hover()
                            await page.wait_for_timeout(1500)
                        except Exception as hover_err:
                            logger.debug(f"Failed to hover warning icon: {hover_err}")
                        
                        # Check for error text in the page after hover
                        error_msg = await page.evaluate("""() => {
                            const bodyText = document.body.innerText;
                            const keywords = ["点数", "AI 点数不足", "余额", "限制", "quota", "limit", "credits", "不足", "额度", "點數", "餘額"];
                            const lines = bodyText.split('\\n').map(l => l.trim()).filter(Boolean);
                            for (const line of lines) {
                                if (keywords.some(k => line.toLowerCase().includes(k)) && line.length < 200) {
                                    return line;
                                }
                            }
                            return null;
                        }""")
                        
                        if not error_msg:
                            # 2. Click if hover didn't reveal the message
                            try:
                                await alert_locator.click()
                                await page.wait_for_timeout(1500)
                                error_msg = await page.evaluate("""() => {
                                    const bodyText = document.body.innerText;
                                    const keywords = ["点数", "AI 点数不足", "余额", "限制", "quota", "limit", "credits", "不足", "额度", "點數", "餘額"];
                                    const lines = bodyText.split('\\n').map(l => l.trim()).filter(Boolean);
                                    for (const line of lines) {
                                        if (keywords.some(k => line.toLowerCase().includes(k)) && line.length < 200) {
                                            return line;
                                        }
                                    }
                                    return null;
                                }""")
                            except Exception as click_err:
                                logger.debug(f"Failed to click warning icon: {click_err}")
                        
                        if error_msg:
                            raise RuntimeError(f"Google Flow video generation blocked by warning: {error_msg}")
                        else:
                            raise RuntimeError("Google Flow video generation blocked. Generate button is replaced by a warning/info icon (possibly insufficient credits/points or prompt length limit).")
                    
                    # Fallback to direct locator if JS traversal failed
                    generate_btn = page.locator("button:has-text('arrow_forward')")
                    if await generate_btn.count() > 0:
                        await generate_btn.first.click(force=True)
                        await page.wait_for_timeout(5000)
                    else:
                        raise RuntimeError(f"Could not find generate button: {click_res.get('error')}")
                else:
                    if click_res.get("isWarning"):
                        logger.warning("Generate button is showing a warning/info state (quota limit or safety block). Waiting to extract warning popup...")
                        await page.wait_for_timeout(2000)
                        warning_text = await page.evaluate("""() => {
                            const dialogs = document.querySelectorAll("[role='dialog'], [role='tooltip'], [class*='popover'], [class*='Tooltip'], [class*='Dialog']");
                            if (dialogs.length > 0) {
                                return Array.from(dialogs).map(d => d.textContent.trim()).join(" | ");
                            }
                            const divs = document.querySelectorAll("div, p, span");
                            const keywords = ["limit", "余额", "限制", "quota", "次", "額度", "每天", "安全", "policy"];
                            for (const d of divs) {
                                if (d.offsetWidth > 0 && d.offsetHeight > 0) {
                                    const text = d.textContent.toLowerCase();
                                    if (keywords.some(k => text.includes(k)) && text.length < 200) {
                                        return d.textContent.trim();
                                    }
                                }
                            }
                            return "Daily generation limit reached, account quota exceeded, or prompt content flag.";
                        }""")
                        raise RuntimeError(f"Google Flow video generation blocked: {warning_text}")
                    else:
                        logger.info("Submitted video generation task successfully via action button.")
                        await page.wait_for_timeout(5000)
                
                # 7. Monitor and wait for new edit link to appear and complete generation
                logger.info("Waiting for video generation task to appear...")
                max_wait = 240  # 4 minutes
                check_interval = 5
                elapsed = 0
                new_link = None
                
                while elapsed < max_wait:
                    # Check and click point approval button if it appears in the chat
                    approve_btn = page.locator("button:has-text('批准'), button:has-text('Approve')")
                    if await approve_btn.count() > 0:
                        for idx in range(await approve_btn.count()):
                            btn = approve_btn.nth(idx)
                            if await btn.is_visible():
                                logger.info(f"Clicking points consumption approval button: '{await btn.inner_text()}'...")
                                await btn.click()
                                await page.wait_for_timeout(2000)
                                break
                                
                    await page.wait_for_timeout(check_interval * 1000)
                    elapsed += check_interval
                    
                    links = page.locator("a")
                    link_count = await links.count()
                    for i in range(link_count):
                        href = await links.nth(i).get_attribute("href")
                        if href and "/edit/" in href and href not in links_before:
                            new_link = href
                            break
                    if new_link:
                        break
                        
                if not new_link:
                    raise RuntimeError("Video generation timed out or failed to output a resource link.")
                    
                logger.info(f"Detected video generation resource link: {new_link}")
                
                # Now wait until the generation percentage indicator disappears from the link text (completed)
                logger.info("Waiting for video generation to reach 100% (completed)...")
                link_locator = page.locator(f"a[href='{new_link}']")
                
                generation_complete = False
                while elapsed < max_wait:
                    count = await link_locator.count()
                    link_texts = []
                    for idx in range(count):
                        try:
                            txt = await link_locator.nth(idx).inner_text()
                            link_texts.append(txt.strip())
                        except Exception:
                            pass
                    
                    combined_text = " | ".join(link_texts)
                    logger.info(f"Current generation status text: '{combined_text.replace(chr(10), ' | ')}'")
                    
                    # Check if ANY of the matched texts contain percentage symbol '%'
                    has_percentage = any("%" in t for t in link_texts)
                    
                    # If none of the texts contain percentage, and we retrieved at least one text, it's completed
                    if not has_percentage and len(link_texts) > 0:
                        logger.info("Generation completed (progress indicator disappeared)!")
                        generation_complete = True
                        break
                        
                    await page.wait_for_timeout(5000)
                    elapsed += 5
                    
                if not generation_complete:
                    logger.warning("Timed out waiting for percentage indicator to disappear, proceeding to navigate anyway...")
                
                # 8. Navigate to the edit resource page to download
                edit_page_url = f"https://labs.google{new_link}" if new_link.startswith("/") else new_link
                logger.info(f"Opening resource detail view for: {new_link}...")
                
                # Try clicking the link first to transition within the SPA smoothly without full page reload
                clicked_spa = False
                try:
                    link_element = page.locator(f"a[href='{new_link}']").first
                    if await link_element.count() > 0:
                        logger.info("Clicking the resource link on page to open detail view...")
                        await link_element.click(timeout=5000)
                        await page.wait_for_timeout(5000)
                        if "/edit/" in page.url:
                            logger.info("Successfully entered edit/detail view via SPA click!")
                            clicked_spa = True
                except Exception as click_err:
                    logger.warning(f"Could not click resource link via SPA: {click_err}")
                
                if not clicked_spa:
                    logger.info(f"Navigating directly to resource download page: {edit_page_url}...")
                    await page.goto(edit_page_url)
                    await page.wait_for_timeout(10000)
                
                # 9. Trigger download and verify format (with self-healing loop for generating states)
                max_dl_attempts = 15
                for attempt in range(max_dl_attempts):
                    logger.info(f"Download attempt {attempt + 1}/{max_dl_attempts}...")
                    
                    download_btn = page.locator(
                        "button:has-text('download'), "
                        "button:has-text('下載'), "
                        "button:has-text('下载'), "
                        "button[aria-label*='download' i], "
                        "button[aria-label*='下載' i], "
                        "button[aria-label*='下载' i], "
                        "button:has([class*='download'])"
                    )
                    item_count = 0
                    
                    # Self-healing: if the download button is not found (we got closed out to the project page),
                    # try to click the resource link on the page to re-open it
                    if await download_btn.count() == 0:
                        logger.warning("Download button not found. Trying to re-open detail view...")
                        try:
                            link_element = page.locator(f"a[href='{new_link}']").first
                            if await link_element.count() > 0:
                                await link_element.click(timeout=5000)
                                await page.wait_for_timeout(3000)
                        except Exception as re_err:
                            logger.warning(f"Could not re-open detail view: {re_err}")
                            
                    if await download_btn.count() == 0:
                        logger.warning("Download button not found yet. Waiting 10s...")
                        await page.wait_for_timeout(10000)
                        continue
                        
                    # Wait for download button to be enabled
                    try:
                        is_disabled = await download_btn.first.get_attribute("disabled")
                        if is_disabled == "true" or is_disabled == "disabled":
                            logger.info("Download button is disabled. Waiting 5s for compilation/activation...")
                            await page.wait_for_timeout(5000)
                            continue
                    except Exception:
                        pass
                        
                    # Trigger download dropdown or direct trigger
                    try:
                        # Click normally first so Playwright does actionability checks
                        await download_btn.first.click(timeout=5000)
                    except Exception as click_err:
                        logger.warning(f"Normal download button click failed: {click_err}. Trying direct DOM dispatch click...")
                        try:
                            el = await download_btn.first.element_handle()
                            if el:
                                await page.evaluate("el => el.click()", el)
                        except Exception as el_err:
                            logger.warning(f"DOM click also failed: {el_err}. Waiting 10s...")
                            await page.wait_for_timeout(10000)
                            continue
                            
                    # Wait up to 3 seconds for the dropdown menu items to appear
                    try:
                        await page.wait_for_selector("[role='menuitem']", state="visible", timeout=3000)
                    except Exception:
                        pass
                        
                    menu_items = page.locator("[role='menuitem']")
                    item_count = await menu_items.count()
                    
                    download_success = False
                    download_val = None
                    
                    try:
                        if item_count > 0:
                            logger.info(f"Detected dropdown menu with {item_count} items. Downloading via menu selection...")
                            target_item = None
                            
                            # Try to find active 2K resolution first, then fallback to 1K
                            for resolution in ["2K", "1K"]:
                                for i in range(item_count):
                                    item = menu_items.nth(i)
                                    text = await item.inner_text()
                                    if resolution in text:
                                        is_disabled = await item.get_attribute("aria-disabled")
                                        if is_disabled != "true":
                                            target_item = item
                                            break
                                if target_item:
                                    break
                                    
                            # Fallback check
                            if not target_item:
                                for i in range(item_count):
                                    item = menu_items.nth(i)
                                    text = await item.inner_text()
                                    if "已產生" in text or "已产生" in text or "原始尺寸" in text or "高清" in text:
                                        is_disabled = await item.get_attribute("aria-disabled")
                                        if is_disabled != "true":
                                            target_item = item
                                            break
                                            
                            if not target_item:
                                target_item = menu_items.first
                                
                            logger.info(f"Selected option text: {await target_item.inner_text()}")
                            async with page.expect_download(timeout=10000) as download_info:
                                await target_item.click()
                            download_val = await download_info.value
                            download_success = True
                        else:
                            logger.info("No dropdown menu detected. Expecting direct download...")
                            async with page.expect_download(timeout=10000) as download_info:
                                # Re-click download button to trigger direct download
                                await download_btn.first.click(force=True)
                            download_val = await download_info.value
                            download_success = True
                    except Exception as trigger_err:
                        logger.warning(f"Download trigger failed/timeout: {trigger_err}. Retrying in 10s...")
                        if item_count > 0:
                            try:
                                await page.keyboard.press("Escape") # Dismiss menu if open
                            except Exception:
                                pass
                        await page.wait_for_timeout(10000)
                        continue
                        
                    if download_success and download_val:
                        os.makedirs(os.path.dirname(output_path), exist_ok=True)
                        temp_dl_path = output_path + ".tmp"
                        if os.path.exists(temp_dl_path):
                            os.remove(temp_dl_path)
                        await download_val.save_as(temp_dl_path)
                        
                        # Verify if the downloaded file is a video (not a JPEG thumbnail)
                        with open(temp_dl_path, "rb") as f:
                            header = f.read(20)
                            
                        if header.startswith(b"\xff\xd8"):
                            logger.info("Downloaded file is a JPEG thumbnail, video generation is likely still in progress. Waiting 15s...")
                            os.remove(temp_dl_path)
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(15000)
                        else:
                            # Successfully got the video!
                            if os.path.exists(output_path):
                                os.remove(output_path)
                            os.rename(temp_dl_path, output_path)
                            logger.info(f"Successfully generated and downloaded Video file to: {output_path} (Header: {header})")
                            return output_path
                            
                raise RuntimeError("Video generation timed out or failed to produce a valid video file download.")
                    
            except Exception as gen_err:
                logger.error(f"Error during Veo video generation: {gen_err}")
                # Save screenshot of error for debugging
                debug_screenshot = os.path.join(self.cookie_dir, "flow_error_screenshot.png")
                try:
                    await page.screenshot(path=debug_screenshot)
                    logger.info(f"Saved Google Flow error screenshot to: {debug_screenshot}")
                except Exception as screenshot_err:
                    logger.error(f"Could not save error screenshot: {screenshot_err}")
                raise gen_err
            finally:
                await browser.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generator = FlowVideoGenerator(headless=True)
    asyncio.run(generator.explore_flow())
