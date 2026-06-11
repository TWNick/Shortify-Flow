import os
import argparse
import logging
import asyncio
from dotenv import load_dotenv

from src.crawler.scraper import Scraper
from src.processor.transcriber import Transcriber
from src.rewriter.agent import ScriptRewriter
from src.renderer.composer import VideoComposer
from src.publisher.uploader import AutoPublisher
import subprocess
import imageio_ffmpeg

def extract_keyframe(video_path, output_image_path, time_offset=2.0):
    """
    Extracts a keyframe image from a video at the specified time offset using ffmpeg.
    """
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-ss", str(time_offset),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        output_image_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception as e:
        logging.getLogger("Shortify-Flow").error(f"Failed to extract keyframe: {e}")
        return False

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Shortify-Flow")

async def run_pipeline(url, topic, voice, publish, search_query=None, target_domain=None, silent_animation=False, commentary=False, flow_video=False):
    """
    Runs the full end-to-end video scraping, rewriting, rendering, and publishing pipeline.
    """
    logger.info("Initializing Shortify-Flow Pipeline...")
    
    scraper = Scraper()
    
    # Detect if search_query itself is a single video URL
    if not url and search_query:
        sq = search_query.strip()
        if sq.startswith("http://") or sq.startswith("https://"):
            # Check if it is a single video and not a search result list page
            if "youtube.com/watch" in sq or "youtu.be/" in sq or "/shorts/" in sq or "tiktok.com/" in sq or "instagram.com/reel/" in sq or "instagram.com/p/" in sq or "facebook.com/" in sq or "fb.watch/" in sq:
                if "/results" not in sq and "search_query" not in sq:
                    logger.info(f"Detected single video URL in search_query: '{sq}'. Directing pipeline to use it as the source URL.")
                    url = sq

    # 1. Automatically find trending video if url is not provided
    if not url:
        if not search_query:
            raise ValueError("Either url or search_query must be provided.")
        logger.info(f"No URL provided. Searching for trending videos with query: '{search_query}'...")
        candidate_urls = scraper.find_trending_shorts_list(search_query)
        if not candidate_urls:
            raise ValueError(f"Could not find any trending short video candidates for query: '{search_query}'")
            
        material = None
        for candidate_url in candidate_urls:
            try:
                material = scraper.download_video(candidate_url)
                if material:
                    url = candidate_url
                    break
            except Exception as dl_err:
                logger.warning(f"Failed to download candidate video {candidate_url}: {dl_err}. Trying next candidate...")
                
        if not material:
            raise ValueError("All candidate videos failed to download.")
    else:
        # 2. Scrape original video material (if url was provided directly)
        material = scraper.download_video(url)
    
    # 3. Transcribe original video to get original script
    transcriber = Transcriber(model_size="base")
    original_transcript = transcriber.transcribe(material["audio_path"])
    logger.info(f"Original Transcript: {original_transcript['text']}")
    
    # 4. Use AI Agent to rewrite script into target topic/domain
    keyframe_path = "workspace/raw_materials/temp_keyframe.png"
    if material and "video_path" in material and os.path.exists(material["video_path"]):
        logger.info(f"Extracting keyframe from original video {material['video_path']} for multimodal analysis...")
        extract_keyframe(material["video_path"], keyframe_path)
    else:
        keyframe_path = None

    rewriter = ScriptRewriter()
    rewritten_script = await rewriter.rewrite_script(
        original_transcript["text"], 
        target_topic=topic if topic else None,
        target_domain=target_domain,
        # Google Flow video uses the same prompt-based scene structure as silent animation
        silent_animation=silent_animation or flow_video,
        commentary=commentary,
        image_path=keyframe_path if keyframe_path and os.path.exists(keyframe_path) else None
    )
    
    # Save mode flag in script data
    rewritten_script["flow_video"] = flow_video
    rewritten_script["silent_animation"] = silent_animation
    rewritten_script["commentary"] = commentary
    
    # 5. Compose and render the new short video
    composer = VideoComposer(voice=voice)
    os.makedirs("workspace/output", exist_ok=True)
    script_path = "workspace/output/rewritten_script.json"
    import json
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(rewritten_script, f, ensure_ascii=False, indent=2)
        
    if flow_video:
        output_video_path = await composer.compose_flow_video(
            script_path,
            output_filename="final_compilation.mp4"
        )
    elif silent_animation:
        output_video_path = await composer.compose_silent_video(
            script_path,
            material["video_path"],
            output_filename="final_compilation.mp4"
        )
    elif commentary:
        output_video_path = await composer.compose_commentary_video(
            script_path,
            material["video_path"],
            output_filename="final_compilation.mp4"
        )
    else:
        output_video_path = await composer.compose(
            rewritten_script["voiceover_text"],
            material["video_path"],
            output_filename="final_compilation.mp4"
        )
    logger.info(f"Successfully generated viral short video at: {output_video_path}")
    
    # 6. Automatically publish the new short video if requested
    if publish:
        publisher = AutoPublisher(platform="youtube", headless=False)
        try:
            title = rewritten_script.get("hook", "Automated Short Video")
            desc_text = rewritten_script.get("voiceover_text", "Created automatically using Shortify-Flow.")
            if not desc_text:
                desc_text = rewritten_script.get("video_concept", "Created automatically using Shortify-Flow.")
            await publisher.publish_youtube_shorts(
                output_video_path,
                title=title,
                description=f"{desc_text[:100]}... #shorts"
            )
            logger.info("Pipeline completed and video published successfully!")
        except Exception as e:
            logger.error(f"Video was generated but publishing failed: {e}")
    else:
        logger.info("Video generation complete. Auto-publishing was not requested.")

async def main():
    parser = argparse.ArgumentParser(description="Shortify-Flow: Automated Short-Video Creation Pipeline")
    parser.add_argument("--action", choices=["run", "login", "login-gemini", "login-flow", "render-only", "upload-only", "rewrite-only", "render-director"], default="run",
                        help="Action to perform: run (full pipeline), login (authenticate accounts), login-gemini, login-flow, rewrite-only, render-director, etc.")
    parser.add_argument("--url", type=str, default=None,
                        help="Target YouTube Shorts or TikTok URL to scrape")
    parser.add_argument("--search-query", type=str, default="coding hacks shorts",
                        help="Search query to find trending shorts if --url is not provided")
    parser.add_argument("--topic", type=str, default=None,
                        help="Target topic to rewrite the script into")
    parser.add_argument("--target-domain", type=str, default=None,
                        help="Target domain to rewrite the script into (e.g. cooking, finance)")
    parser.add_argument("--voice", type=str, default=None,
                        help="TTS Voice name (Edge-TTS compatible). If not specified, a random high-quality voice will be chosen.")
    parser.add_argument("--publish", action="store_true",
                        help="Automatically upload and publish the video once rendered")
    parser.add_argument("--video-path", type=str, help="Path to video (for upload-only or render-only)")
    parser.add_argument("--text", type=str, help="Narration text (for render-only)")
    parser.add_argument("--silent-animation", action="store_true",
                        help="Enable silent animation mode (no voiceover, dynamic zoom/pan, background music)")
    parser.add_argument("--commentary", action="store_true",
                        help="Enable funny animal commentary mode with AI voiceover mixed with original audio")
    parser.add_argument("--flow-video", action="store_true",
                        help="Use Google Flow (Veo) to generate original video scenes")

    args = parser.parse_args()

    if not args.voice:
        import random
        voices = [
            "en-US-ChristopherNeural",
            "en-US-GuyNeural",
            "en-US-JennyNeural",
            "en-US-AriaNeural",
            "en-GB-SoniaNeural",
            "en-GB-RyanNeural"
        ]
        args.voice = random.choice(voices)
        logger.info(f"No voice specified. Randomly assigned high-quality voice: {args.voice}")

    if args.action == "login":
        publisher = AutoPublisher(platform="youtube", headless=False)
        await publisher.save_login_session()
        
    elif args.action == "login-gemini":
        rewriter = ScriptRewriter(headless=False)
        await rewriter.save_login_session()
        
    elif args.action == "login-flow":
        from src.rewriter.flow_generator import FlowVideoGenerator
        generator = FlowVideoGenerator(headless=False)
        await generator.save_login_session()
        
    elif args.action == "run":
        if not args.url and not args.search_query:
            parser.error("Either --url or --search-query is required for running the pipeline")
        await run_pipeline(
            args.url, 
            args.topic, 
            args.voice, 
            args.publish, 
            search_query=args.search_query, 
            target_domain=args.target_domain,
            silent_animation=args.silent_animation,
            commentary=args.commentary,
            flow_video=args.flow_video
        )
        
    elif args.action == "rewrite-only":
        if not args.url and not args.search_query:
            parser.error("Either --url or --search-query is required for rewrite-only")
        
        logger.info("Initializing rewrite-only pipeline...")
        scraper = Scraper()
        url = args.url
        if not url:
            sq = args.search_query.strip()
            if sq.startswith("http://") or sq.startswith("https://"):
                if "youtube.com/watch" in sq or "youtu.be/" in sq or "/shorts/" in sq or "tiktok.com/" in sq or "instagram.com/reel/" in sq or "instagram.com/p/" in sq or "facebook.com/" in sq or "fb.watch/" in sq:
                    if "/results" not in sq and "search_query" not in sq:
                        logger.info(f"Detected single video URL in search_query: '{sq}'. Directing pipeline to use it as the source URL.")
                        url = sq

        if not url:
            logger.info(f"No URL provided. Searching for trending videos with query: '{args.search_query}'...")
            candidate_urls = scraper.find_trending_shorts_list(args.search_query)
            if not candidate_urls:
                raise ValueError(f"Could not find any trending short video candidates for query: '{args.search_query}'")
                
            material = None
            for candidate_url in candidate_urls:
                try:
                    material = scraper.download_video(candidate_url)
                    if material:
                        url = candidate_url
                        break
                except Exception as dl_err:
                    logger.warning(f"Failed to download candidate video {candidate_url}: {dl_err}. Trying next candidate...")
            
            if not material:
                raise ValueError("All candidate videos failed to download.")
        else:
            material = scraper.download_video(url)
        transcriber = Transcriber(model_size="base")
        original_transcript = transcriber.transcribe(material["audio_path"])
        logger.info(f"Original Transcript: {original_transcript['text']}")
        
        keyframe_path = "workspace/raw_materials/temp_keyframe.png"
        if material and "video_path" in material and os.path.exists(material["video_path"]):
            logger.info(f"Extracting keyframe from original video {material['video_path']} for multimodal analysis...")
            extract_keyframe(material["video_path"], keyframe_path)
        else:
            keyframe_path = None

        rewriter = ScriptRewriter()
        rewritten_script = await rewriter.rewrite_script(
            original_transcript["text"], 
            target_topic=args.topic if args.topic else None,
            target_domain=args.target_domain,
            silent_animation=args.silent_animation or args.flow_video,
            commentary=args.commentary,
            image_path=keyframe_path if keyframe_path and os.path.exists(keyframe_path) else None
        )
        
        # Save mode flag in script data
        rewritten_script["flow_video"] = args.flow_video
        rewritten_script["silent_animation"] = args.silent_animation
        rewritten_script["commentary"] = args.commentary
        
        # Save to file
        os.makedirs("workspace/output", exist_ok=True)
        script_path = "workspace/output/rewritten_script.json"
        import json
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(rewritten_script, f, ensure_ascii=False, indent=2)
        logger.info(f"Rewritten script saved successfully to: {script_path}")
        
    elif args.action == "render-director":
        script_path = "workspace/output/rewritten_script.json"
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Rewritten script JSON not found at: {script_path}")
            
        logger.info("Initializing render-director pipeline...")
        composer = VideoComposer(voice=args.voice)
        
        # Read script data to determine if silent animation is enabled
        import json
        with open(script_path, 'r', encoding='utf-8') as f:
            script_data = json.load(f)
            
        is_flow = script_data.get("flow_video", False) or args.flow_video
        is_silent = script_data.get("silent_animation", False)
        is_commentary = script_data.get("commentary", False)
        
        if is_flow:
            output_video_path = await composer.compose_flow_video(
                script_path,
                output_filename="final_compilation.mp4"
            )
        elif is_silent:
            output_video_path = await composer.compose_silent_animation(
                script_path,
                output_filename="final_compilation.mp4"
            )
        elif is_commentary:
            output_video_path = await composer.compose_commentary_video(
                script_path,
                args.video_path if args.video_path else "workspace/raw_materials/temp_bg.mp4", # Fallback logic
                output_filename="final_compilation.mp4"
            )
        else:
            output_video_path = await composer.compose_from_images(
                script_path,
                output_filename="final_compilation.mp4"
            )
            
        logger.info(f"Successfully generated director short video at: {output_video_path}")
        
        if args.publish:
            publisher = AutoPublisher(platform="youtube", headless=False)
            try:
                title = script_data.get("hook", "Automated Short Video")
                # For description, use video concept in silent mode
                desc_text = script_data.get("video_concept", "Created automatically using Shortify-Flow.")
                await publisher.publish_youtube_shorts(
                    output_video_path,
                    title=title,
                    description=f"{desc_text[:100]}... #shorts"
                )
                logger.info("Pipeline completed and video published successfully!")
            except Exception as e:
                logger.error(f"Video was generated but publishing failed: {e}")
                
    elif args.action == "render-only":
        if not args.video_path or not args.text:
            parser.error("--video-path and --text are required for render-only")
        composer = VideoComposer(voice=args.voice)
        res = await composer.compose(args.text, args.video_path, "custom_render.mp4")
        logger.info(f"Rendered custom video at: {res}")
        
    elif args.action == "upload-only":
        if not args.video_path:
            parser.error("--video-path is required for upload-only")
        publisher = AutoPublisher(platform="youtube", headless=False)
        await publisher.publish_youtube_shorts(
            args.video_path,
            title="Automated YouTube Short",
            description="Created automatically using Shortify-Flow. #shorts"
        )

if __name__ == "__main__":
    asyncio.run(main())
