import os
import logging
import json
import re
import asyncio
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

def robust_json_parse(text):
    try:
        return json.loads(text)
    except Exception as parse_err:
        logger.warning(f"Standard JSON parse failed: {parse_err}. Attempting robust extraction...")
        
    # Extract fields using regex
    concept_match = re.search(r'"video_concept"\s*:\s*"(.*?)"\s*,\s*"target_topic"', text, re.DOTALL)
    if not concept_match:
        concept_match = re.search(r'"video_concept"\s*:\s*"(.*?)"\s*,', text, re.DOTALL)
    video_concept = concept_match.group(1).strip() if concept_match else ""
    
    topic_match = re.search(r'"target_topic"\s*:\s*"(.*?)"\s*,\s*"hook"', text, re.DOTALL)
    if not topic_match:
        topic_match = re.search(r'"target_topic"\s*:\s*"(.*?)"\s*,', text, re.DOTALL)
    target_topic = topic_match.group(1).strip() if topic_match else ""
    
    hook_match = re.search(r'"hook"\s*:\s*"(.*?)"\s*,\s*"voiceover_text"', text, re.DOTALL)
    if not hook_match:
        hook_match = re.search(r'"hook"\s*:\s*"(.*?)"\s*,', text, re.DOTALL)
    hook = hook_match.group(1).strip() if hook_match else ""
    
    voiceover_match = re.search(r'"voiceover_text"\s*:\s*"(.*?)"\s*,\s*"scenes"', text, re.DOTALL)
    if not voiceover_match:
        voiceover_match = re.search(r'"voiceover_text"\s*:\s*"(.*?)"\s*,', text, re.DOTALL)
    voiceover_text = voiceover_match.group(1).strip() if voiceover_match else ""
    
    scenes = []
    scenes_start = text.find('"scenes"')
    if scenes_start != -1:
        scenes_text = text[scenes_start:]
        scene_blocks = re.findall(r'\{\s*(.*?)\s*\}', scenes_text, re.DOTALL)
        for block in scene_blocks:
            if "prompt" not in block:
                continue
                
            start_match = re.search(r'"start_pct"\s*:\s*([0-9.]+)', block)
            start_pct = float(start_match.group(1)) if start_match else 0.0
            
            end_match = re.search(r'"end_pct"\s*:\s*([0-9.]+)', block)
            end_pct = float(end_match.group(1)) if end_match else 0.0
            
            # Match prompt (handles unescaped quotes)
            prompt_match = re.search(r'"prompt"\s*:\s*"(.*?)"\s*,\s*"(?:overlay_text|narration)"', block, re.DOTALL)
            if not prompt_match:
                prompt_match = re.search(r'"prompt"\s*:\s*"(.*)"', block, re.DOTALL)
            
            prompt_val = ""
            if prompt_match:
                prompt_val = prompt_match.group(1).strip()
            
            overlay_match = re.search(r'"(?:overlay_text|narration)"\s*:\s*"(.*?)"', block, re.DOTALL)
            overlay_val = overlay_match.group(1).strip() if overlay_match else ""
                
            scene_dict = {
                "start_pct": start_pct,
                "end_pct": end_pct,
                "prompt": prompt_val,
                "overlay_text": overlay_val
            }
            if "narration" in block:
                scene_dict["narration"] = overlay_val
                
            scenes.append(scene_dict)
            
    reconstructed = {
        "video_concept": video_concept,
        "target_topic": target_topic,
        "hook": hook,
        "voiceover_text": voiceover_text,
        "scenes": scenes
    }
    
    if not video_concept and not target_topic and not scenes:
        raise ValueError("Robust parser failed to extract any valid fields from response.")
        
    return reconstructed

class ScriptRewriter:
    def __init__(self, cookie_dir="workspace/cookies", headless=True):
        self.cookie_dir = cookie_dir
        os.makedirs(self.cookie_dir, exist_ok=True)
        self.cookie_path = os.path.join(self.cookie_dir, "gemini.json")
        self.headless = headless

    async def save_login_session(self):
        """
        Opens a browser in GUI mode to let the user log in to Google/Gemini manually.
        Monitors cookies to detect successful authentication and saves state automatically.
        """
        logger.info("Starting login session for Google Gemini...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()
            
            await page.goto("https://gemini.google.com/app")
            print("=========================================================")
            print(" [自動偵測登入] 瀏覽器已在您的桌面開啟。")
            print(" 請在瀏覽器中登入您的 Google 帳號。")
            print(" 一旦您成功登入並進入 Gemini 聊天界面，本程式將會：")
            print(" 1. 自動儲存 Cookie。")
            print(" 2. 自動關閉瀏覽器視窗。")
            print(" 3. 繼續背景工作。")
            print("=========================================================")
            
            max_wait_seconds = 300  # 5 minutes
            check_interval = 2.0
            elapsed = 0
            login_success = False
            
            while elapsed < max_wait_seconds:
                try:
                    if page.is_closed():
                        logger.warning("Browser window was closed by the user.")
                        break
                        
                    current_url = page.url
                    cookies = await context.cookies()
                    has_sid = any(c['name'] in ['__Secure-1PSID', '__Secure-3PSID', 'SID'] for c in cookies)
                    
                    if has_sid and "gemini.google.com" in current_url:
                        logger.info("Successfully detected authenticated Google session cookies!")
                        login_success = True
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
                logger.info(f"Saved login session cookies to {self.cookie_path}")
            else:
                logger.warning("Could not verify successful login within the timeout period or browser was closed.")
                
            await browser.close()

    async def rewrite_script(self, original_transcript, target_topic=None, target_domain=None, silent_animation=False, commentary=False, retry_on_signin=True, image_path=None):
        """
        Takes the original transcript and rewrites it into a new viral short-video script
        using browser automation to talk to Gemini web interface.
        Returns a structured JSON dict.
        """
        logger.info("Initializing script rewriting via Gemini browser automation...")
        
        # Clean sensitive/violent/profane words from original_transcript to prevent Google safety filter block (Error 1076)
        cleaned_transcript = original_transcript
        sensitive_patterns = {
            r'\bkill\b': 'defeat',
            r'\bfuck(er|ing|ed)?\b': 'mess',
            r'\bbitch\b': 'dog',
            r'\bshit\b': 'crap',
            r'\bass(hole)?\b': 'back',
            r'\bsex\b': 'gender'
        }
        for pattern, repl in sensitive_patterns.items():
            cleaned_transcript = re.sub(pattern, repl, cleaned_transcript, flags=re.IGNORECASE)
        
        if not os.path.exists(self.cookie_path):
            logger.warning("No cookies found for Gemini. Triggering interactive login session...")
            await self.save_login_session()
            if not os.path.exists(self.cookie_path):
                raise FileNotFoundError("Authentication cookies not found even after login session.")

        if silent_animation:
            if image_path:
                system_prompt = (
                    "You are an expert short-video growth hacker and content creator.\n"
                    "Your task is to analyze a successful viral short-video transcript, and rewrite it into a NEW similar script that is a SILENT ANIMATION video. This means there is NO voiceover or narration. The message must be conveyed ENTIRELY through dynamic visual actions and very short bold text overlays on screen (e.g., 1-3 words or symbols).\n\n"
                    
                    "DYNAMIC MULTIMODAL VISUAL REQUIREMENT:\n"
                    "1. We have uploaded a reference image from the source video. You MUST analyze this image to identify the main subject/character (e.g., a cat, a dog, a specific object, a developer) and the background/environment/scene (e.g., a cardboard box in a living room, a desk, an outdoor field).\n"
                    "2. You MUST use the exact main subject and background environment found in the uploaded image as the visual theme for all scenes in this video! Do NOT use default human workspace templates unless the uploaded image actually shows a human workspace. The video scenes must show this specific subject performing the new topic's actions.\n"
                    "3. Every scene's prompt must describe a repetitive action featuring this subject that can loop seamlessly (using words like 'seamless loop', 'looping motion', 'cinemagraph loop'). Everything must look like real life (photorealistic, real-life footage style, cinematic lighting, 9:16 vertical aspect ratio).\n"
                    "4. PROMPT LENGTH LIMIT: The entire text of the 'prompt' value MUST be extremely short, concise, and strictly under 230 characters! If it exceeds 230 characters, the generation will fail. Combine the style and action description very compactly.\n"
                    "5. SCRIPT LOOPING: The last scene of the video must seamlessly loop back to the first scene. The ending prompt and overlay text must logically transition back into the starting scene, creating a perfect infinite loop when the video repeats.\n\n"
                )
            else:
                system_prompt = (
                    "You are an expert short-video growth hacker and content creator. "
                    "Your task is to analyze a successful viral short-video transcript, "
                    "understand its pacing, engagement hooks (especially the first 3 seconds), "
                    "and call-to-actions, and then rewrite it into a NEW similar script "
                    "that is a SILENT ANIMATION video. This means there is NO voiceover or narration. "
                    "The message must be conveyed ENTIRELY through dynamic visual actions and very short bold text overlays on screen (e.g., 1-3 words or symbols).\n\n"
                    
                    "STYLE & INFINITE LOOP REQUIREMENT:\n"
                    "1. You MUST choose exactly ONE photorealistic visual style for the entire video from the list below to keep all scenes visually consistent, and include its exact description in every scene's prompt. Everything must look like real life.\n"
                    "2. Every scene's prompt must describe a repetitive action that can loop seamlessly (using words like 'seamless loop', 'looping motion', 'cinemagraph loop').\n"
                    "3. PROMPT LENGTH LIMIT: The entire text of the 'prompt' value MUST be extremely short, concise, and strictly under 230 characters! If it exceeds 230 characters, the generation will fail. Make sure your scene action descriptions are very brief and to the point.\n"
                    "4. SCRIPT LOOPING: The last scene of the video must seamlessly loop back to the first scene. The ending prompt and overlay text must logically transition back into the starting scene, creating a perfect infinite loop when the video repeats.\n\n"
                    "Choose from one of these 5 realistic loop templates:\n"
                    "- Style 1 (Realistic Workspace Loop): Real-life footage, modern workspace, cinematic lighting, 9:16 vertical, seamless loop.\n"
                    "- Style 2 (Realistic City Cinemagraph): Real-life city street, central subject in cinemagraph loop, 9:16 vertical, seamless loop.\n"
                    "- Style 3 (Realistic Cozy Home Loop): Real-life cozy home, warm window light, 9:16 vertical, seamless loop.\n"
                    "- Style 4 (Realistic Outdoor Travel Loop): Real-life outdoor travel, scenic view, sunlight, 9:16 vertical, seamless loop.\n"
                    "- Style 5 (Realistic Studio Close-Up Loop): Commercial studio close-up, professional lighting, 9:16 vertical, seamless loop.\n\n"
                )
            
            if target_domain:
                system_prompt += (
                    f"CRITICAL REQUIREMENT: You MUST translate and rewrite this transcript into a COMPLETELY DIFFERENT domain: '{target_domain}'. "
                    "Keep the exact same hook structure, pacing, and viral formatting, but swap all tech/coding examples with equivalents from the new domain.\n\n"
                )

            system_prompt += (
                "You MUST output ONLY a valid JSON object with the following schema, and NO other conversational text. Do not wrap it in markdown code blocks other than standard json:\n"
                "{\n"
                "  \"video_concept\": \"Brief description of the new silent animation video concept\",\n"
                "  \"target_topic\": \"The topic chosen/given\",\n"
                "  \"hook\": \"The first visual text overlay designed to grab attention (e.g., STOP!, FAIL!, LOOK!)\",\n"
                "  \"voiceover_text\": \"\",\n"
                "  \"scenes\": [\n"
                "    {\n"
                "      \"start_pct\": 0.0, \n"
                "      \"end_pct\": 0.15,\n"
                "      \"prompt\": \"Concise prompt for video generation. Combine the chosen style description and the looping action. MUST BE UNDER 230 CHARACTERS TOTAL.\",\n"
                "      \"overlay_text\": \"Extremely short visual overlay text to be printed in bold on screen (e.g., SLICE!, TRY THIS, BOOM!, FIXED!)\"\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "Ensure the sum of scenes covers 100% of the video duration (from start_pct 0.0 to end_pct 1.0).\n\n"
                f"Original Transcript:\n{cleaned_transcript}\n\n"
            )
        elif commentary:
            system_prompt = (
                "You are an expert short-video growth hacker and content creator specializing in viral animal memes. "
                "Your task is to analyze a successful viral short-video transcript, understand its pacing and hooks, "
                "and rewrite it into a FUNNY ANIMAL COMMENTARY / DUBBING script. This means you will create a hilarious, "
                "first-person voiceover monologue representing the thoughts of the animal in the video (e.g., a sassy dog, "
                "a drama-queen cat, or a confused panda). It must feel like the animal is talking directly to the viewer or to itself.\n\n"
                "CRITICAL REQUIREMENT: Keep the pace extremely high, use funny exclamations, sarcastic remarks, and comical drama. "
                "The target domain is animals/pets.\n\n"
            )
            
            system_prompt += (
                "You MUST output ONLY a valid JSON object with the following schema, and NO other conversational text. Do not wrap it in markdown code blocks other than standard json:\n"
                "{\n"
                "  \"video_concept\": \"Brief description of the funny animal commentary concept\",\n"
                "  \"target_topic\": \"Funny animal commentary / dubbing\",\n"
                "  \"hook\": \"A punchy, attention-grabbing title or first line (first 3 seconds)\",\n"
                "  \"voiceover_text\": \"The complete hilarious narration spoken by the animal or narrator throughout the video\",\n"
                "  \"scenes\": [\n"
                "    {\n"
                "      \"start_pct\": 0.0, \n"
                "      \"end_pct\": 0.15,\n"
                "      \"prompt\": \"Description of what the animal is physically doing in the video during this segment (e.g., Cat slipping off table, looking shocked)\",\n"
                "      \"narration\": \"The specific funny line or thought spoken during this segment\"\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "Ensure the sum of scenes covers 100% of the video duration (from start_pct 0.0 to end_pct 1.0).\n\n"
                f"Original Transcript:\n{cleaned_transcript}\n\n"
            )
        else:
            system_prompt = (
                "You are an expert short-video growth hacker and content creator. "
                "Your task is to analyze a successful viral short-video transcript, "
                "understand its pacing, engagement hooks (especially the first 3 seconds), "
                "and call-to-actions, and then rewrite it into a NEW similar script.\n\n"
            )
            
            if target_domain:
                system_prompt += (
                    f"CRITICAL REQUIREMENT: You MUST translate and rewrite this transcript into a COMPLETELY DIFFERENT domain: '{target_domain}'. "
                    "For example, if the original video is about programming or tech, rewrite it to be about cooking, gardening, finance, fitness, or general life hacks. "
                    "Keep the exact same hook structure, pacing, and viral formatting, but swap all tech/coding examples with equivalents from the new domain.\n\n"
                )

            system_prompt += (
                "You MUST output ONLY a valid JSON object with the following schema, and NO other conversational text. Do not wrap it in markdown code blocks other than standard json:\n"
                "{\n"
                "  \"video_concept\": \"Brief description of the new video concept\",\n"
                "  \"target_topic\": \"The topic chosen/given\",\n"
                "  \"hook\": \"The first sentence (first 3 seconds) designed to grab attention\",\n"
                "  \"voiceover_text\": \"The complete narration text of the video\",\n"
                "  \"scenes\": [\n"
                "    {\n"
                "      \"start_pct\": 0.0, \n"
                "      \"end_pct\": 0.15,\n"
                "      \"prompt\": \"Detailed descriptive prompt for generating a background image or video segment for this scene\",\n"
                "      \"narration\": \"The specific narration sentence spoken during this scene\"\n"
                "    }\n"
                "  ]\n"
                "}\n"
                "Ensure the sum of scenes covers 100% of the video duration (from start_pct 0.0 to end_pct 1.0).\n\n"
                f"Original Transcript:\n{cleaned_transcript}\n\n"
            )

        if target_topic:
            system_prompt += f"Target Topic for Rewrite: {target_topic}\n"
        elif target_domain:
            system_prompt += f"Target Topic: Choose a trending topic within the '{target_domain}' domain.\n"
        else:
            system_prompt += "Target Topic: Choose a trending developer, productivity, or tech-hack topic.\n"
            
        # Always forbid referencing external files or image filenames to prevent Google Flow assets mismatch errors
        system_prompt += "\nCRITICAL: You MUST NOT reference any image filenames (e.g. image_0.png, image_1.png, keyframe.png, input_file_0.png) in the 'prompt' fields of the generated scenes. Describe all visual subjects, characters, and settings textually instead. Do not assume any files are uploaded to the generation workspace.\n"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(
                storage_state=self.cookie_path,
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()
            
            try:
                logger.info("Opening Gemini Web App...")
                await page.goto("https://gemini.google.com/app")
                await page.wait_for_timeout(3000)
                
                # Check for signin page or "Sign in" button indicating expired cookies
                signin_btn = page.locator("a:has-text('Sign in'), button:has-text('Sign in'), a:has-text('登入'), button:has-text('登入'), a:has-text('登录'), button:has-text('登录')")
                is_signin_page = "signin" in page.url or "accounts.google.com" in page.url
                
                if is_signin_page or await signin_btn.count() > 0:
                    if retry_on_signin:
                        logger.warning("Gemini session expired or unauthorized. Triggering interactive login session...")
                        await browser.close()
                        
                        # Delete expired cookies
                        if os.path.exists(self.cookie_path):
                            try:
                                logger.info(f"Removing expired cookie file: {self.cookie_path}")
                                os.remove(self.cookie_path)
                            except Exception as rm_err:
                                logger.warning(f"Failed to remove expired cookie file: {rm_err}")
                                
                        await self.save_login_session()
                        return await self.rewrite_script(original_transcript, target_topic, target_domain, silent_animation, commentary, retry_on_signin=False)
                    else:
                        raise RuntimeError(f"Failed to authenticate to Gemini even after triggering login session. Current URL: {page.url}")
                
                # Wait for prompt box
                prompt_input = page.locator('div[contenteditable="true"]:not(.ql-clipboard)')
                await prompt_input.wait_for(timeout=20000)
                logger.info("Successfully loaded Gemini chat interface. Waiting 8s for WS connection to stabilize...")
                await page.wait_for_timeout(8000)
                
                # Dismiss any welcome overlays or consent modals on page load
                welcome_btns = page.locator("button:has-text('開始使用'), button:has-text('开始使用'), button:has-text('同意'), button:has-text('Agree'), button:has-text('確定'), button:has-text('确定')")
                if await welcome_btns.count() > 0:
                    for idx in range(await welcome_btns.count()):
                        btn = welcome_btns.nth(idx)
                        if await btn.is_visible():
                            logger.info(f"Dismissing welcome modal by clicking button: '{await btn.inner_text()}'")
                            await btn.click()
                            await page.wait_for_timeout(2000)
                
                # Locate response messages before sending the prompt (using tag names message-content, model-response, and class .model-response-text)
                response_locator = page.locator('message-content, model-response, .model-response-text')
                initial_count = await response_locator.count()
                
                # Try clicking "New chat" only if there are existing messages to ensure a fresh session and avoid session errors
                if initial_count > 0:
                    new_chat_btn = page.locator("a, button, div, span").filter(
                        has_text=re.compile("^(新對話|New chat|新建对话)$")
                    ).first
                    if await new_chat_btn.count() > 0 and await new_chat_btn.is_visible():
                        logger.info("Clicking 'New chat' button to clear history and start a fresh session...")
                        try:
                            await new_chat_btn.click(timeout=3000)
                            await page.wait_for_timeout(4000)  # Give extra time for backend session initialization
                            # Re-locate prompt input just in case DOM refreshed
                            prompt_input = page.locator('div[contenteditable="true"]:not(.ql-clipboard)')
                            await prompt_input.wait_for(timeout=10000)
                            initial_count = 0  # Reset initial_count since history is cleared
                        except Exception as nc_err:
                            logger.warning(f"Could not click New chat button: {nc_err}")
                # Upload reference image if provided for multimodal analysis
                if image_path and os.path.exists(image_path):
                    logger.info(f"Uploading visual reference image: {image_path}")
                    try:
                        # Locate plus button using stable class or wildcard test-id roles safely
                        plus_btn = page.locator(
                            "button[data-test-id='actions-menu-button'], "
                            "button[aria-label*='多功能功能表'], "
                            "button[aria-label*='Upload' i], "
                            "button[aria-label*='Add' i], "
                            "button[aria-label*='上傳' i], "
                            "button[aria-label*='新增' i], "
                            "button:has-text('+')"
                        ).filter(visible=True).first
                        
                        try:
                            # Dismiss any transient overlay dialogs first
                            await page.keyboard.press("Escape")
                            await plus_btn.click(timeout=3000)
                        except Exception as click_err:
                            logger.warning(f"Normal plus button click failed: {click_err}. Trying direct DOM dispatch click...")
                            el = await plus_btn.element_handle()
                            if el:
                                await page.evaluate("el => el.click()", el)
                        await page.wait_for_timeout(1500)
                        
                        # Locate upload option using Unicode escapes for Chinese "上傳檔案" / "上传文件"
                        upload_option = page.locator("span, div, li, button, [role='menuitem']").filter(
                            has_text=re.compile(r"^(Upload files|Upload file|\u4e0a\u50b3\u6a94\u6848|\u4e0a\u4f20\u6587\u4ef6)$")
                        ).filter(visible=True).first
                        
                        # Handle file chooser with fallback clicking
                        async with page.expect_file_chooser() as fc_info:
                            try:
                                await upload_option.click(timeout=3000)
                            except Exception as opt_click_err:
                                logger.warning(f"Normal upload option click failed: {opt_click_err}. Trying direct DOM dispatch click...")
                                opt_el = await upload_option.element_handle()
                                if opt_el:
                                    await page.evaluate("el => el.click()", opt_el)
                                else:
                                    raise opt_click_err
                        file_chooser = await fc_info.value
                        await file_chooser.set_files(image_path)
                        logger.info("Reference image selected successfully. Waiting 6s for upload to complete...")
                        await page.wait_for_timeout(6000)
                        
                        # Click "同意" (Agree/Consent) button if upload consent modal appears
                        consent_btn = page.locator("button:has-text('同意'), button:has-text('Agree')")
                        if await consent_btn.count() > 0:
                            for idx in range(await consent_btn.count()):
                                btn = consent_btn.nth(idx)
                                if await btn.is_visible():
                                    logger.info("Detected upload consent modal. Clicking '同意'...")
                                    await btn.click()
                                    await page.wait_for_timeout(2000)
                                    break
                    except Exception as upload_err:
                        logger.warning(f"Could not upload visual reference image: {upload_err}. Continuing with text only...")
                
                # Input the prompt
                # Click "同意" (Agree/Consent) or any welcome buttons if they are still visible
                consent_btns = page.locator("button:has-text('同意'), button:has-text('Agree'), button:has-text('開始使用'), button:has-text('开始使用'), button:has-text('確定'), button:has-text('确定')")
                if await consent_btns.count() > 0:
                    for idx in range(await consent_btns.count()):
                        btn = consent_btns.nth(idx)
                        if await btn.is_visible():
                            logger.info(f"Dismissing modal overlay before prompt entry: '{await btn.inner_text()}'")
                            await btn.click()
                            await page.wait_for_timeout(2000)
                            
                await prompt_input.click()
                await prompt_input.fill(system_prompt)
                await page.wait_for_timeout(1000)
                
                # Ensure input state sync in React/Lit
                await prompt_input.focus()
                await page.keyboard.press("Space")
                await page.keyboard.press("Backspace")
                await page.wait_for_timeout(1000)
                
                # Click send button or press enter
                send_btn = page.locator(
                    'button[aria-label="Send prompt"], '
                    'button[aria-label="Send message"], '
                    'button[aria-label="Send"], '
                    'button[aria-label="傳送訊息"], '
                    'button[aria-label="傳送提示詞"], '
                    'button[aria-label="傳送"], '
                    'button[aria-label="发送消息"], '
                    'button[aria-label="发送提示词"], '
                    'button[aria-label="发送"]'
                )
                
                # Check for visible send button
                visible_send_btn = None
                if await send_btn.count() > 0:
                    for i in range(await send_btn.count()):
                        btn = send_btn.nth(i)
                        if await btn.is_visible():
                            visible_send_btn = btn
                            break
                            
                if visible_send_btn:
                    logger.info("Clicking Send button...")
                    try:
                        await visible_send_btn.click(timeout=5000, force=True)
                    except Exception as click_err:
                        logger.warning(f"Could not click send button: {click_err}. Will try evaluating click...")
                        try:
                            el = await visible_send_btn.element_handle()
                            if el:
                                await page.evaluate("el => el.click()", el)
                        except Exception as eval_err:
                            logger.warning(f"Evaluate click failed: {eval_err}")
                else:
                    logger.info("Send button not found or not visible.")
                    
                # Helper function to check for Gemini errors (e.g. 1076)
                async def check_for_gemini_errors():
                    error_toast = page.locator("div, span, p").filter(has_text=re.compile("(發生錯誤|發生了錯誤|An error occurred|1076)", re.IGNORECASE))
                    visible_error = False
                    if await error_toast.count() > 0:
                        for idx in range(await error_toast.count()):
                            if await error_toast.nth(idx).is_visible():
                                visible_error = True
                                err_txt = await error_toast.nth(idx).inner_text()
                                logger.error(f"Gemini server returned error: {err_txt}")
                                break
                    if visible_error:
                        if os.path.exists(self.cookie_path):
                            try:
                                os.remove(self.cookie_path)
                                logger.info("Removed expired cookies due to server error.")
                            except Exception as rm_err:
                                logger.warning(f"Failed to remove cookie path: {rm_err}")
                        raise RuntimeError("Gemini server returned 1076 or other session error. Cookie removed to trigger re-login.")

                # Wait for the new response to start appearing
                logger.info("Waiting for Gemini response to start...")
                start_time = asyncio.get_event_loop().time()
                started = False
                while asyncio.get_event_loop().time() - start_time < 15:
                    if await response_locator.count() > initial_count:
                        started = True
                        break
                    await check_for_gemini_errors()
                    await asyncio.sleep(0.5)
                    
                if not started:
                    logger.warning("Gemini did not start responding after clicking. Trying keyboard fallback (Control+Enter)...")
                    await prompt_input.focus()
                    await page.keyboard.press("Control+Enter")
                    
                    # Wait again 5s
                    start_time = asyncio.get_event_loop().time()
                    while asyncio.get_event_loop().time() - start_time < 5:
                        if await response_locator.count() > initial_count:
                            started = True
                            break
                        await check_for_gemini_errors()
                        await asyncio.sleep(0.5)
                        
                if not started:
                    logger.warning("Still not responding. Trying keyboard fallback (Enter)...")
                    await prompt_input.focus()
                    await page.keyboard.press("Enter")
                    
                    # Wait again 5s
                    start_time = asyncio.get_event_loop().time()
                    while asyncio.get_event_loop().time() - start_time < 5:
                        if await response_locator.count() > initial_count:
                            started = True
                            break
                        await check_for_gemini_errors()
                        await asyncio.sleep(0.5)
                        
                if not started:
                    raise TimeoutError("Gemini did not start responding in time.")
                    
                latest_response = response_locator.last
                
                # Wait for response text to stabilize
                logger.info("Streaming response from Gemini... Waiting for completion...")
                last_text = ""
                stable_count = 0
                max_wait_time = 90
                wait_start = asyncio.get_event_loop().time()
                
                while asyncio.get_event_loop().time() - wait_start < max_wait_time:
                    current_text = await latest_response.inner_text()
                    current_text = current_text.strip()
                    
                    if current_text and current_text == last_text:
                        stable_count += 1
                        if stable_count >= 6: # stable for 3 seconds (6 * 0.5s)
                            stop_btn = page.locator('button[aria-label*="Stop"], button[aria-label*="stop"], button[aria-label*="停止"], button[aria-label*="中断"]')
                            if await stop_btn.count() == 0 or not await stop_btn.first.is_visible():
                                break
                    else:
                        stable_count = 0
                        last_text = current_text
                        
                    await asyncio.sleep(0.5)
                    
                raw_text = await latest_response.inner_text()
                logger.info("Gemini response completed.")
                
                # Parse JSON out of the response using robust helper
                script_data = robust_json_parse(raw_text)
                logger.info("Successfully parsed rewritten script JSON from Gemini web response.")
                
                # Save state ONLY on success path
                try:
                    state = await context.storage_state()
                    with open(self.cookie_path, 'w', encoding='utf-8') as f:
                        json.dump(state, f)
                    logger.info(f"Updated Gemini storage state successfully.")
                except Exception as save_err:
                    logger.warning(f"Could not save updated storage state: {save_err}")
                    
                return script_data
                
            except Exception as e:
                logger.error(f"Error during script rewriting via Gemini Web: {e}")
                # Save screenshot of error for debugging
                debug_screenshot = os.path.join(self.cookie_dir, "gemini_error_screenshot.png")
                try:
                    await page.screenshot(path=debug_screenshot)
                    logger.info(f"Saved Gemini error screenshot to: {debug_screenshot}")
                except Exception as screenshot_err:
                    logger.error(f"Could not save error screenshot: {screenshot_err}")
                raise e
            finally:
                await browser.close()
