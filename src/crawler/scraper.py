import os
import logging
import imageio_ffmpeg
from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)

class Scraper:
    def __init__(self, output_dir="workspace/raw_materials"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def download_video(self, url):
        """
        Downloads a video (YouTube Shorts or TikTok) and returns the paths to the downloaded files.
        We download bestvideo+bestaudio and merge them, as well as extract audio separately for transcription.
        """
        logger.info(f"Starting download for URL: {url}")
        
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        # Options to download video and audio merged
        video_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(self.output_dir, '%(title)s_%(id)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': ffmpeg_exe,
        }
        
        # Options to extract audio separately (e.g. as mp3 or wav for transcription)
        audio_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(self.output_dir, '%(title)s_%(id)s_audio.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': ffmpeg_exe,
        }

        # Support cookies file from environment variables (e.g. for Facebook or YouTube)
        cookie_file = os.getenv("DOWNLOAD_COOKIES_PATH")
        if cookie_file and os.path.exists(cookie_file):
            video_opts['cookiefile'] = cookie_file
            audio_opts['cookiefile'] = cookie_file
            logger.info(f"Using cookies file for download: {cookie_file}")

        try:
            # 1. Download merged video
            with YoutubeDL(video_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                video_filename = ydl.prepare_filename(info)
                # If merged, the extension might change to mp4
                video_path = os.path.splitext(video_filename)[0] + ".mp4"
                if not os.path.exists(video_path):
                    video_path = video_filename
                logger.info(f"Downloaded video to: {video_path}")

            # 2. Download audio for transcription
            with YoutubeDL(audio_opts) as ydl:
                info_audio = ydl.extract_info(url, download=True)
                audio_filename = ydl.prepare_filename(info_audio)
                # Postprocessor converts to .wav
                audio_path = os.path.splitext(audio_filename)[0] + "_audio.wav"
                # Sometimes yt-dlp output path layout is different, let's verify
                if not os.path.exists(audio_path):
                    audio_path = os.path.splitext(audio_filename)[0] + ".wav"
                logger.info(f"Downloaded audio to: {audio_path}")

            return {
                "title": info.get("title", "Unknown"),
                "id": info.get("id", ""),
                "description": info.get("description", ""),
                "video_path": os.path.abspath(video_path),
                "audio_path": os.path.abspath(audio_path)
            }
        except Exception as e:
            # If download fails and it is a Facebook URL, try fallback with Chrome/Edge browser cookies
            if "facebook.com" in url or "fb.watch" in url:
                logger.warning("Facebook download failed. Retrying with browser cookies fallback...")
                for browser in ['chrome', 'edge']:
                    try:
                        logger.info(f"Attempting download retry using cookies from browser: {browser}...")
                        retry_video_opts = video_opts.copy()
                        retry_audio_opts = audio_opts.copy()
                        retry_video_opts['cookiesfrombrowser'] = (browser,)
                        retry_audio_opts['cookiesfrombrowser'] = (browser,)
                        
                        with YoutubeDL(retry_video_opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                            video_filename = ydl.prepare_filename(info)
                            video_path = os.path.splitext(video_filename)[0] + ".mp4"
                            if not os.path.exists(video_path):
                                video_path = video_filename
                                
                        with YoutubeDL(retry_audio_opts) as ydl:
                            info_audio = ydl.extract_info(url, download=True)
                            audio_filename = ydl.prepare_filename(info_audio)
                            audio_path = os.path.splitext(audio_filename)[0] + "_audio.wav"
                            if not os.path.exists(audio_path):
                                audio_path = os.path.splitext(audio_filename)[0] + ".wav"
                                
                        logger.info(f"Successfully downloaded Facebook video using {browser} cookies!")
                        return {
                            "title": info.get("title", "Unknown"),
                            "id": info.get("id", ""),
                            "description": info.get("description", ""),
                            "video_path": os.path.abspath(video_path),
                            "audio_path": os.path.abspath(audio_path)
                        }
                    except Exception as retry_err:
                        logger.warning(f"Retry with {browser} cookies failed: {retry_err}")
            
            logger.error(f"Failed to download video from {url}: {e}")
            raise e

    def find_trending_shorts_list(self, query="coding shorts", max_results=30):
        """
        Searches YouTube for shorts using the query, filters by duration,
        and returns a list of candidate URLs sorted by view count (highest first).
        """
        logger.info(f"Searching for trending shorts with query: {query}")
        
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': ffmpeg_exe,
        }
        
        try:
            with YoutubeDL(ydl_opts) as ydl:
                # If query is already a URL, use it directly (e.g. YouTube search with filter parameters)
                if query.startswith("http://") or query.startswith("https://"):
                    search_url = query
                else:
                    search_url = f"ytsearch{max_results}:{query}"
                info = ydl.extract_info(search_url, download=False)
                
                if not info or 'entries' not in info or not info['entries']:
                    logger.warning("No search results found.")
                    return []
                
                candidates = []
                for entry in info['entries']:
                    if not entry:
                        continue
                    
                    title = entry.get('title', '')
                    duration = entry.get('duration')
                    view_count = entry.get('view_count', 0) or 0
                    
                    logger.info(f"Found search result: '{title}' - Duration: {duration}s - Views: {view_count}")
                    
                    # Filter: Shorts must be under 65 seconds and not be live streams (which have no duration)
                    if not duration:
                        logger.info(f"Skipping '{title}' because duration is None (likely live stream).")
                        continue
                    if duration > 65:
                        logger.info(f"Skipping '{title}' because duration {duration}s > 65s")
                        continue
                        
                    url = entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}"
                    candidates.append((view_count, url, title))
                
                # Sort candidates by view count descending
                candidates.sort(key=lambda x: x[0], reverse=True)
                
                if candidates:
                    logger.info(f"Found {len(candidates)} candidate videos matching Shorts criteria.")
                    return [c[1] for c in candidates]
                else:
                    logger.warning("No video matched the Shorts duration filter.")
                    return []
        except Exception as e:
            logger.error(f"Failed to find trending shorts: {e}")
            return []

    def find_trending_short(self, query="coding shorts", max_results=30):
        """
        Searches YouTube for shorts using the query, filters by duration,
        and returns the url of the video with the highest view count.
        """
        urls = self.find_trending_shorts_list(query, max_results)
        return urls[0] if urls else None

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scraper = Scraper()
    # Simple test case (using a short public video)
    test_url = "https://www.youtube.com/shorts/5u7S7H6eZ9E"
    try:
        res = scraper.download_video(test_url)
        print("Success:", res)
    except Exception as e:
        print("Failed:", e)
