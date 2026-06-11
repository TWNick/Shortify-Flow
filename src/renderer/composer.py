import os
import logging
import subprocess
import asyncio
import edge_tts
import imageio_ffmpeg
from moviepy import AudioFileClip
from src.processor.transcriber import Transcriber

logger = logging.getLogger(__name__)

class VideoComposer:
    def __init__(self, output_dir="workspace/output", voice="en-US-ChristopherNeural"):
        self.output_dir = output_dir
        self.voice = voice
        os.makedirs(self.output_dir, exist_ok=True)
        # We will use the transcriber to get word-level timestamps on synthesized voiceovers
        self.transcriber = Transcriber(model_size="base")

    async def generate_voiceover(self, text, output_path):
        """
        Synthesizes speech voiceover using edge-tts.
        """
        logger.info(f"Synthesizing voiceover: '{text[:50]}...' using voice '{self.voice}'")
        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(output_path)
        logger.info(f"Voiceover saved to: {output_path}")

    def create_highlighted_srt(self, transcription_result, srt_path):
        """
        Generates an SRT file where the currently spoken word is highlighted in yellow.
        """
        logger.info(f"Creating highlighted SRT file: {srt_path}")
        srt_entries = []
        entry_idx = 1
        
        for segment in transcription_result["segments"]:
            words = segment.get("words", [])
            if not words:
                # Fallback to segment-level timestamp if no word timestamps
                start_str = self._format_timestamp(segment["start"])
                end_str = self._format_timestamp(segment["end"])
                srt_entries.append(f"{entry_idx}\n{start_str} --> {end_str}\n{segment['text']}\n")
                entry_idx += 1
                continue
                
            # For each word, generate a subtitle entry showing the whole segment text with the active word highlighted
            for i, active_word in enumerate(words):
                start_str = self._format_timestamp(active_word["start"])
                end_str = self._format_timestamp(active_word["end"])
                
                # Reconstruct the sentence, highlighting the active word
                highlighted_words = []
                for w_idx, w in enumerate(words):
                    word_text = w["word"].strip()
                    if w_idx == i:
                        highlighted_words.append(f'<b><font color="#FFDD00">{word_text}</font></b>')
                    else:
                        highlighted_words.append(word_text)
                
                sentence = " ".join(highlighted_words)
                srt_entries.append(f"{entry_idx}\n{start_str} --> {end_str}\n{sentence}\n")
                entry_idx += 1
                
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
        logger.info("SRT file written successfully.")

    def _format_timestamp(self, seconds):
        """
        Formats seconds into SRT timestamp format: HH:MM:SS,mmm
        """
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

    def get_audio_duration(self, audio_path):
        """
        Queries the duration of an audio file using moviepy.
        """
        clip = AudioFileClip(audio_path)
        duration = clip.duration
        clip.close()
        return duration

    def assemble_video(self, background_video_path, voiceover_audio_path, srt_path, output_video_path):
        """
        Assembles the final vertical 9:16 video using FFmpeg.
        - Cuts the background video to match the voiceover audio duration.
        - Crops the background video to vertical 9:16 (e.g. 1080x1920 or centered crop).
        - Merges the voiceover audio track.
        - Burns in the highlighted SRT subtitles.
        """
        logger.info("Assembling video using FFmpeg...")
        duration = self.get_audio_duration(voiceover_audio_path)
        logger.info(f"Video duration will be: {duration:.2f} seconds")

        # Temporal output paths
        temp_cropped = os.path.join(self.output_dir, "temp_cropped.mp4")
        if os.path.exists(temp_cropped):
            os.remove(temp_cropped)
        if os.path.exists(output_video_path):
            os.remove(output_video_path)

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        # Step 1: Crop background video to 9:16 and cut duration
        # We centered-crop to 9:16: 'ih*9/16' width, 'ih' height
        crop_filter = "crop=ih*9/16:ih:(iw-ow)/2:(ih-oh)/2"
        crop_cmd = [
            ffmpeg_exe, '-y', '-i', background_video_path,
            '-t', str(duration), '-vf', crop_filter,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
            '-an', temp_cropped
        ]
        
        logger.info(f"Executing crop command: {' '.join(crop_cmd)}")
        subprocess.run(crop_cmd, check=True)

        # Step 2: Merge voiceover audio and burn subtitles
        # To avoid escaping issues on Windows, we convert backslashes to forward slashes in srt_path for the ffmpeg subtitle filter
        srt_ffmpeg_path = srt_path.replace('\\', '/')
        if ':' in srt_ffmpeg_path:
            # On Windows, drive letters like C:/ must be escaped as C\\:/
            drive, path_part = srt_ffmpeg_path.split(':', 1)
            srt_ffmpeg_path = f"{drive}\\:{path_part}"
            
        subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='Alignment=2,FontSize=16,Outline=1,Shadow=1'"
        
        merge_cmd = [
            ffmpeg_exe, '-y', '-i', temp_cropped, '-i', voiceover_audio_path,
            '-vf', subtitle_filter, '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
            '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0', '-shortest',
            output_video_path
        ]
        
        logger.info(f"Executing merge & subtitle burn command: {' '.join(merge_cmd)}")
        subprocess.run(merge_cmd, check=True)
        
        # Cleanup temporary files
        if os.path.exists(temp_cropped):
            os.remove(temp_cropped)
            
        logger.info(f"Successfully assembled video at: {output_video_path}")

    def create_scene_clip(self, image_path, duration, output_path, zoom=False):
        """
        Converts a static image to a 9:16 vertical MP4 video clip of a specific duration using FFmpeg.
        Can optionally apply a smooth Ken Burns (zoom-in) effect.
        """
        logger.info(f"Creating scene clip from {image_path} with duration {duration:.2f}s, zoom={zoom}")
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        if zoom:
            # First scale up, then zoompan, outputting 1080x1920 to avoid low-res stretch issues
            vf_filter = "scale=1920:3413,zoompan=z='min(zoom+0.001,1.2)':x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':d=125:s=1080x1920"
        else:
            # Scale and crop to 1080x1920 (9:16)
            vf_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
        
        cmd = [
            ffmpeg_exe, '-y',
            '-loop', '1',
            '-i', image_path,
            '-t', f"{duration:.2f}",
            '-vf', vf_filter,
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            '-r', '25',
            output_path
        ]
        
        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        logger.info(f"Scene clip created successfully at: {output_path}")

    def get_video_duration(self, video_path):
        """
        Queries the duration of a video file using moviepy.
        """
        from moviepy import VideoFileClip
        clip = VideoFileClip(video_path)
        duration = clip.duration
        clip.close()
        return duration

    async def compose_silent_video(self, rewritten_script_path, background_video_path, output_filename="result_shorts.mp4"):
        """
        Composes a silent viral video from a real background video by burning central meme subtitles,
        cropping to 9:16, and retaining the original audio.
        """
        logger.info(f"Composing silent video from real footage: {background_video_path} using script: {rewritten_script_path}")
        
        import json
        with open(rewritten_script_path, 'r', encoding='utf-8') as f:
            script = json.load(f)
            
        scenes = script["scenes"]
        total_duration = self.get_video_duration(background_video_path)
        logger.info(f"Source video duration: {total_duration:.2f} seconds")
        
        srt_path = os.path.join(self.output_dir, "subtitles.srt")
        output_video_path = os.path.join(self.output_dir, output_filename)
        
        # 1. Create simple SRT using overlay_text aligned to video percentages
        srt_entries = []
        for idx, scene in enumerate(scenes):
            start_pct = scene["start_pct"]
            end_pct = scene["end_pct"]
            overlay_text = scene.get("overlay_text", "")
            
            start_time = total_duration * start_pct
            end_time = total_duration * end_pct
            if idx == len(scenes) - 1:
                end_time = total_duration
                
            start_str = self._format_timestamp(start_time)
            end_str = self._format_timestamp(end_time)
            
            formatted_text = f'<b><font color="#FFDD00">{overlay_text}</font></b>'
            srt_entries.append(f"{idx+1}\n{start_str} --> {end_str}\n{formatted_text}\n")
            
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
            
        # 2. Crop to 9:16, burn subtitles, and copy original audio using FFmpeg
        if os.path.exists(output_video_path):
            os.remove(output_video_path)
            
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        srt_ffmpeg_path = srt_path.replace('\\', '/')
        if ':' in srt_ffmpeg_path:
            drive, path_part = srt_ffmpeg_path.split(':', 1)
            srt_ffmpeg_path = f"{drive}\\:{path_part}"
            
        crop_filter = "crop=ih*9/16:ih:(iw-ow)/2:(ih-oh)/2"
        subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='Alignment=5,FontSize=32,Outline=2,Shadow=1'"
        
        cmd = [
            ffmpeg_exe, '-y',
            '-i', background_video_path,
            '-vf', f"{crop_filter},{subtitle_filter}",
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '20',
            '-c:a', 'aac',
            output_video_path
        ]
        
        logger.info(f"Running FFmpeg silent video merge: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        logger.info(f"Silent real video composed successfully at: {output_video_path}")
        
        return output_video_path

    async def compose_commentary_video(self, rewritten_script_path, background_video_path, output_filename="result_shorts.mp4"):
        """
        Composes a viral commentary video from a real background video by mixing AI voiceover,
        original background audio, and burning word-highlighted subtitles.
        """
        logger.info(f"Composing commentary video from real footage: {background_video_path} using script: {rewritten_script_path}")
        
        import json
        with open(rewritten_script_path, 'r', encoding='utf-8') as f:
            script = json.load(f)
            
        voiceover_text = script["voiceover_text"]
        
        voiceover_path = os.path.join(self.output_dir, "voiceover.wav")
        srt_path = os.path.join(self.output_dir, "subtitles.srt")
        output_video_path = os.path.join(self.output_dir, output_filename)
        
        # 1. Synthesize voiceover
        await self.generate_voiceover(voiceover_text, voiceover_path)
        
        # 2. Get precise timestamps via local transcription
        transcription_res = self.transcriber.transcribe(voiceover_path)
        
        # 3. Create highlighted SRT
        self.create_highlighted_srt(transcription_res, srt_path)
        
        # 4. Get voiceover duration
        duration = self.get_audio_duration(voiceover_path)
        logger.info(f"Video duration will be: {duration:.2f} seconds based on voiceover")
        
        # 5. Crop background video to 9:16 and cut duration (without audio for temporary video)
        temp_cropped = os.path.join(self.output_dir, "temp_cropped.mp4")
        if os.path.exists(temp_cropped):
            os.remove(temp_cropped)
        if os.path.exists(output_video_path):
            os.remove(output_video_path)
            
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        crop_filter = "crop=ih*9/16:ih:(iw-ow)/2:(ih-oh)/2"
        crop_cmd = [
            ffmpeg_exe, '-y', '-i', background_video_path,
            '-t', str(duration), '-vf', crop_filter,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
            '-an', temp_cropped
        ]
        
        logger.info(f"Executing crop command: {' '.join(crop_cmd)}")
        subprocess.run(crop_cmd, check=True)
        
        # 6. Mix original audio and AI voiceover, then burn subtitles
        srt_ffmpeg_path = srt_path.replace('\\', '/')
        if ':' in srt_ffmpeg_path:
            drive, path_part = srt_ffmpeg_path.split(':', 1)
            srt_ffmpeg_path = f"{drive}\\:{path_part}"
            
        subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='Alignment=2,FontSize=16,Outline=1,Shadow=1'"
        
        # Mix audio tracks
        filter_complex = (
            f"[1:a]volume=0.3[a0];[2:a]volume=1.2[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[music];"
            f"[0:v]{subtitle_filter}[video]"
        )
        
        merge_cmd = [
            ffmpeg_exe, '-y',
            '-i', temp_cropped,
            '-i', background_video_path,
            '-i', voiceover_path,
            '-filter_complex', filter_complex,
            '-map', '[video]',
            '-map', '[music]',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
            '-c:a', 'aac', '-shortest',
            output_video_path
        ]
        
        logger.info(f"Executing mix & subtitle burn command: {' '.join(merge_cmd)}")
        subprocess.run(merge_cmd, check=True)
        
        # Cleanup temporary files
        if os.path.exists(temp_cropped):
            os.remove(temp_cropped)
            
        logger.info(f"Successfully assembled commentary video at: {output_video_path}")
        return output_video_path

    def download_bgm(self, bgm_path):
        """
        Downloads a royalty-free energetic background music track if not present.
        """
        if os.path.exists(bgm_path):
            logger.info(f"BGM already exists at {bgm_path}")
            return
        logger.info(f"Downloading royalty-free BGM to {bgm_path}...")
        import urllib.request
        url = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3"
        try:
            urllib.request.urlretrieve(url, bgm_path)
            logger.info("BGM downloaded successfully.")
        except Exception as e:
            logger.warning(f"Failed to download BGM: {e}. A silent audio track will be used.")
            # Fallback: create silent audio using ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [
                ffmpeg_exe, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:c=2',
                '-t', '15', bgm_path
            ]
            subprocess.run(cmd, check=True)

    def download_all_bgms(self, bgm_dir="workspace/bgm"):
        """
        Downloads several royalty-free background music tracks to the bgm directory.
        """
        os.makedirs(bgm_dir, exist_ok=True)
        import urllib.request
        
        bgm_urls = {
            "bgm_1.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
            "bgm_2.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
            "bgm_3.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-8.mp3",
            "bgm_4.mp3": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-12.mp3"
        }
        
        for name, url in bgm_urls.items():
            path = os.path.join(bgm_dir, name)
            if not os.path.exists(path):
                logger.info(f"Downloading BGM track {name} from {url}...")
                try:
                    urllib.request.urlretrieve(url, path)
                except Exception as e:
                    logger.warning(f"Failed to download {name}: {e}. Creating a fallback silent track.")
                    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                    cmd = [
                        ffmpeg_exe, '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:c=2',
                        '-t', '15', path
                    ]
                    subprocess.run(cmd, check=True)

    def get_random_bgm(self, bgm_dir="workspace/bgm"):
        """
        Downloads all BGMs if missing, and returns the path to a randomly selected BGM.
        """
        self.download_all_bgms(bgm_dir)
        import random
        bgm_files = [f for f in os.listdir(bgm_dir) if f.endswith(".mp3")]
        if not bgm_files:
            fallback_path = os.path.join(self.output_dir, "viral_bgm.mp3")
            self.download_bgm(fallback_path)
            return fallback_path
            
        selected_bgm = random.choice(bgm_files)
        selected_path = os.path.abspath(os.path.join(bgm_dir, selected_bgm))
        logger.info(f"Randomly selected background music: {selected_path}")
        return selected_path

    async def compose_silent_animation(self, rewritten_script_path, output_filename="result_shorts.mp4"):
        """
        Coordinates the compilation of silent animation shorts using visual overlay text,
        Ken Burns camera effects, and background music.
        """
        logger.info(f"Composing silent animation from script: {rewritten_script_path}")
        
        import json
        with open(rewritten_script_path, 'r', encoding='utf-8') as f:
            script = json.load(f)
            
        scenes = script["scenes"]
        
        total_duration = 15.0 # Fixed duration for silent shorts
        bgm_path = self.get_random_bgm()
        
        srt_path = os.path.join(self.output_dir, "subtitles.srt")
        output_video_path = os.path.join(self.output_dir, output_filename)
        
        # 1. Create simple SRT using overlay_text
        srt_entries = []
        for idx, scene in enumerate(scenes):
            start_pct = scene["start_pct"]
            end_pct = scene["end_pct"]
            overlay_text = scene.get("overlay_text", "")
            
            start_time = total_duration * start_pct
            end_time = total_duration * end_pct
            if idx == len(scenes) - 1:
                end_time = total_duration
                
            start_str = self._format_timestamp(start_time)
            end_str = self._format_timestamp(end_time)
            
            # Wrap overlay text in HTML tags for extra visual weight
            formatted_text = f'<b><font color="#FFDD00">{overlay_text}</font></b>'
            srt_entries.append(f"{idx+1}\n{start_str} --> {end_str}\n{formatted_text}\n")
            
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_entries))
            
        # 2. Compile scene clips with Zoompan effect
        temp_clips = []
        try:
            for idx, scene in enumerate(scenes):
                start_pct = scene["start_pct"]
                end_pct = scene["end_pct"]
                image_path = scene.get("image_path")
                
                if not image_path or not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image path for scene {idx} is missing or invalid: {image_path}")
                    
                start_time = total_duration * start_pct
                end_time = total_duration * end_pct
                if idx == len(scenes) - 1:
                    end_time = total_duration
                    
                scene_duration = max(0.1, end_time - start_time)
                
                scene_clip_path = os.path.join(self.output_dir, f"temp_scene_{idx}.mp4")
                self.create_scene_clip(image_path, scene_duration, scene_clip_path, zoom=True)
                temp_clips.append(scene_clip_path)
                
            # 3. Concatenate scene clips
            concat_list_path = os.path.join(self.output_dir, "concat_list.txt")
            with open(concat_list_path, 'w', encoding='utf-8') as f_list:
                for clip_path in temp_clips:
                    abs_path = os.path.abspath(clip_path).replace('\\', '/')
                    f_list.write(f"file '{abs_path}'\n")
                    
            temp_background = os.path.join(self.output_dir, "temp_background.mp4")
            if os.path.exists(temp_background):
                os.remove(temp_background)
                
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            concat_cmd = [
                ffmpeg_exe, '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_list_path,
                '-c', 'copy',
                temp_background
            ]
            subprocess.run(concat_cmd, check=True)
            
            # 4. Burn subtitles and mix BGM
            srt_ffmpeg_path = srt_path.replace('\\', '/')
            if ':' in srt_ffmpeg_path:
                drive, path_part = srt_ffmpeg_path.split(':', 1)
                srt_ffmpeg_path = f"{drive}\\:{path_part}"
                
            subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='Alignment=5,FontSize=32,Outline=2,Shadow=1'"
            
            if os.path.exists(output_video_path):
                os.remove(output_video_path)
                
            # Mix background music, trim to 15s and apply a 2s fade out
            merge_cmd = [
                ffmpeg_exe, '-y',
                '-i', temp_background,
                '-i', bgm_path,
                '-filter_complex', f"[1:a]atrim=end=15,afade=t=out:st=13:d=2[music];[0:v]{subtitle_filter}[video]",
                '-map', '[video]',
                '-map', '[music]',
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '20',
                '-c:a', 'aac',
                '-shortest',
                output_video_path
            ]
            
            logger.info(f"Running final merge & subtitle burn (silent animation): {' '.join(merge_cmd)}")
            subprocess.run(merge_cmd, check=True)
            
        finally:
            # Cleanup temp files
            for temp_clip in temp_clips:
                if os.path.exists(temp_clip):
                    try:
                        os.remove(temp_clip)
                    except Exception as e:
                        logger.warning(f"Could not remove temp clip {temp_clip}: {e}")
                        
            concat_list_path = os.path.join(self.output_dir, "concat_list.txt")
            if os.path.exists(concat_list_path):
                try:
                    os.remove(concat_list_path)
                except Exception as e:
                    logger.warning(f"Could not remove concat list file: {e}")
                    
            temp_background = os.path.join(self.output_dir, "temp_background.mp4")
            if os.path.exists(temp_background):
                try:
                    os.remove(temp_background)
                except Exception as e:
                    logger.warning(f"Could not remove temp background file: {e}")
                    
        return output_video_path

    async def compose_from_images(self, rewritten_script_path, output_filename="result_shorts.mp4"):
        """
        Coordinates the compilation of video from static images and a voiceover text
        specified in the rewritten script JSON file.
        """
        logger.info(f"Composing video from images using script: {rewritten_script_path}")
        
        import json
        with open(rewritten_script_path, 'r', encoding='utf-8') as f:
            script = json.load(f)
            
        voiceover_text = script["voiceover_text"]
        scenes = script["scenes"]
        
        voiceover_path = os.path.join(self.output_dir, "voiceover.wav")
        srt_path = os.path.join(self.output_dir, "subtitles.srt")
        output_video_path = os.path.join(self.output_dir, output_filename)
        
        # 1. Synthesize voiceover
        await self.generate_voiceover(voiceover_text, voiceover_path)
        
        # 2. Get precise timestamps via local transcription
        transcription_res = self.transcriber.transcribe(voiceover_path)
        
        # 3. Create highlighted SRT
        self.create_highlighted_srt(transcription_res, srt_path)
        
        # 4. Get total duration
        total_duration = self.get_audio_duration(voiceover_path)
        logger.info(f"Total audio duration: {total_duration:.2f} seconds")
        
        # 5. Create scene clips based on start_pct and end_pct
        temp_clips = []
        try:
            for idx, scene in enumerate(scenes):
                start_pct = scene["start_pct"]
                end_pct = scene["end_pct"]
                image_path = scene.get("image_path")
                
                if not image_path or not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image path for scene {idx} is missing or invalid: {image_path}")
                    
                # Calculate duration
                start_time = total_duration * start_pct
                end_time = total_duration * end_pct
                
                # For the last scene, make sure it ends exactly at total_duration to avoid gaps
                if idx == len(scenes) - 1:
                    end_time = total_duration
                    
                scene_duration = max(0.1, end_time - start_time)
                
                scene_clip_path = os.path.join(self.output_dir, f"temp_scene_{idx}.mp4")
                self.create_scene_clip(image_path, scene_duration, scene_clip_path, zoom=False)
                temp_clips.append(scene_clip_path)
                
            # 6. Concatenate scene clips
            # We will use FFmpeg concat demuxer
            concat_list_path = os.path.join(self.output_dir, "concat_list.txt")
            with open(concat_list_path, 'w', encoding='utf-8') as f_list:
                for clip_path in temp_clips:
                    abs_path = os.path.abspath(clip_path).replace('\\', '/')
                    f_list.write(f"file '{abs_path}'\n")
                    
            temp_background = os.path.join(self.output_dir, "temp_background.mp4")
            if os.path.exists(temp_background):
                os.remove(temp_background)
                
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            concat_cmd = [
                ffmpeg_exe, '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_list_path,
                '-c', 'copy',
                temp_background
            ]
            
            logger.info(f"Running FFmpeg concat: {' '.join(concat_cmd)}")
            subprocess.run(concat_cmd, check=True)
            
            # 7. Merge voiceover and burn subtitles
            srt_ffmpeg_path = srt_path.replace('\\', '/')
            if ':' in srt_ffmpeg_path:
                drive, path_part = srt_ffmpeg_path.split(':', 1)
                srt_ffmpeg_path = f"{drive}\\:{path_part}"
                
            subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='Alignment=2,FontSize=16,Outline=1,Shadow=1'"
            
            if os.path.exists(output_video_path):
                os.remove(output_video_path)
                
            merge_cmd = [
                ffmpeg_exe, '-y',
                '-i', temp_background,
                '-i', voiceover_path,
                '-vf', subtitle_filter,
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '20',
                '-c:a', 'aac',
                '-map', '0:v:0',
                '-map', '1:a:0',
                '-shortest',
                output_video_path
            ]
            
            logger.info(f"Running final merge & subtitle burn: {' '.join(merge_cmd)}")
            subprocess.run(merge_cmd, check=True)
            
        finally:
            # Cleanup temp files
            for temp_clip in temp_clips:
                if os.path.exists(temp_clip):
                    try:
                        os.remove(temp_clip)
                    except Exception as e:
                        logger.warning(f"Could not remove temp clip {temp_clip}: {e}")
            
            concat_list_path = os.path.join(self.output_dir, "concat_list.txt")
            if os.path.exists(concat_list_path):
                try:
                    os.remove(concat_list_path)
                except Exception as e:
                    logger.warning(f"Could not remove concat list file: {e}")
                    
            temp_background = os.path.join(self.output_dir, "temp_background.mp4")
            if os.path.exists(temp_background):
                try:
                    os.remove(temp_background)
                except Exception as e:
                    logger.warning(f"Could not remove temp background file: {e}")
                    
        return output_video_path

    async def compose_flow_video(self, rewritten_script_path, output_filename="result_shorts.mp4"):
        """
        Coordinates the compilation of original video clips generated via Google Flow (Veo).
        Supports both silent mode (with background music) and voiceover mode (with synthesized speech).
        """
        logger.info(f"Composing original Google Flow video from script: {rewritten_script_path}")
        
        import json
        with open(rewritten_script_path, 'r', encoding='utf-8') as f:
            script = json.load(f)
            
        scenes = script["scenes"]
        voiceover_text = script.get("voiceover_text", "")
        
        output_video_path = os.path.join(self.output_dir, output_filename)
        voiceover_path = os.path.join(self.output_dir, "voiceover.wav")
        srt_path = os.path.join(self.output_dir, "subtitles.srt")
        bgm_path = None # Will be randomly assigned if silent animation
        
        has_voiceover = bool(voiceover_text.strip())
        
        if has_voiceover:
            # 1. Synthesize voiceover
            await self.generate_voiceover(voiceover_text, voiceover_path)
            # 2. Get precise timestamps via local transcription
            transcription_res = self.transcriber.transcribe(voiceover_path)
            # 3. Create highlighted SRT
            self.create_highlighted_srt(transcription_res, srt_path)
            # 4. Get total duration
            total_duration = self.get_audio_duration(voiceover_path)
            logger.info(f"Total voiceover duration: {total_duration:.2f} seconds")
        else:
            total_duration = 15.0 # Fixed duration for silent animation
            bgm_path = self.get_random_bgm()
            # Create simple SRT using overlay_text
            srt_entries = []
            for idx, scene in enumerate(scenes):
                start_pct = scene["start_pct"]
                end_pct = scene["end_pct"]
                overlay_text = scene.get("overlay_text", "")
                
                start_time = total_duration * start_pct
                end_time = total_duration * end_pct
                if idx == len(scenes) - 1:
                    end_time = total_duration
                    
                start_str = self._format_timestamp(start_time)
                end_str = self._format_timestamp(end_time)
                
                formatted_text = f'<b><font color="#FFDD00">{overlay_text}</font></b>'
                srt_entries.append(f"{idx+1}\n{start_str} --> {end_str}\n{formatted_text}\n")
                
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(srt_entries))
                
        # 5. Generate video clips via Google Flow
        from src.rewriter.flow_generator import FlowVideoGenerator
        flow_gen = FlowVideoGenerator(headless=True)
        
        temp_clips = []
        try:
            for idx, scene in enumerate(scenes):
                start_pct = scene["start_pct"]
                end_pct = scene["end_pct"]
                prompt = scene.get("prompt")
                
                if not prompt:
                    prompt = "A beautiful aesthetic abstract scene, 3d animation"
                
                start_time = total_duration * start_pct
                end_time = total_duration * end_pct
                if idx == len(scenes) - 1:
                    end_time = total_duration
                    
                scene_duration = max(0.1, end_time - start_time)
                scene_clip_path = os.path.join(self.output_dir, f"temp_flow_scene_{idx}.mp4")
                
                logger.info(f"Scene {idx}: Generating video for prompt: '{prompt}' (Duration: {scene_duration:.2f}s)")
                await flow_gen.generate_scene_video(prompt, scene_duration, scene_clip_path)
                
                processed_clip_path = os.path.join(self.output_dir, f"processed_flow_scene_{idx}.mp4")
                
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                crop_filter = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
                proc_cmd = [
                    ffmpeg_exe, '-y', '-i', scene_clip_path,
                    '-t', f"{scene_duration:.2f}",
                    '-vf', crop_filter,
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', '25',
                    '-an', processed_clip_path
                ]
                logger.info(f"Post-processing Veo output: {' '.join(proc_cmd)}")
                subprocess.run(proc_cmd, check=True)
                
                if os.path.exists(scene_clip_path):
                    os.remove(scene_clip_path)
                    
                temp_clips.append(processed_clip_path)
                
            # 6. Concatenate video clips
            concat_list_path = os.path.join(self.output_dir, "concat_list.txt")
            with open(concat_list_path, 'w', encoding='utf-8') as f_list:
                for clip_path in temp_clips:
                    abs_path = os.path.abspath(clip_path).replace('\\', '/')
                    f_list.write(f"file '{abs_path}'\n")
                    
            temp_background = os.path.join(self.output_dir, "temp_background.mp4")
            if os.path.exists(temp_background):
                os.remove(temp_background)
                
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            concat_cmd = [
                ffmpeg_exe, '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_list_path,
                '-c', 'copy',
                temp_background
            ]
            subprocess.run(concat_cmd, check=True)
            
            # 7. Burn subtitles and mix audio
            srt_ffmpeg_path = srt_path.replace('\\', '/')
            if ':' in srt_ffmpeg_path:
                drive, path_part = srt_ffmpeg_path.split(':', 1)
                srt_ffmpeg_path = f"{drive}\\:{path_part}"
                
            if has_voiceover:
                subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='Alignment=2,FontSize=16,Outline=1,Shadow=1'"
                if os.path.exists(output_video_path):
                    os.remove(output_video_path)
                merge_cmd = [
                    ffmpeg_exe, '-y',
                    '-i', temp_background,
                    '-i', voiceover_path,
                    '-vf', subtitle_filter,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                    '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0', '-shortest',
                    output_video_path
                ]
            else:
                subtitle_filter = f"subtitles='{srt_ffmpeg_path}':force_style='Alignment=5,FontSize=32,Outline=2,Shadow=1'"
                if os.path.exists(output_video_path):
                    os.remove(output_video_path)
                merge_cmd = [
                    ffmpeg_exe, '-y',
                    '-i', temp_background,
                    '-i', bgm_path,
                    '-filter_complex', f"[1:a]atrim=end=15,afade=t=out:st=13:d=2[music];[0:v]{subtitle_filter}[video]",
                    '-map', '[video]',
                    '-map', '[music]',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                    '-c:a', 'aac', '-shortest',
                    output_video_path
                ]
                
            logger.info(f"Running final merge (flow video): {' '.join(merge_cmd)}")
            subprocess.run(merge_cmd, check=True)
            
        finally:
            for temp_clip in temp_clips:
                if os.path.exists(temp_clip):
                    try:
                        os.remove(temp_clip)
                    except Exception as e:
                        logger.warning(f"Could not remove temp clip {temp_clip}: {e}")
                        
            concat_list_path = os.path.join(self.output_dir, "concat_list.txt")
            if os.path.exists(concat_list_path):
                try:
                    os.remove(concat_list_path)
                except Exception:
                    pass
                    
            temp_background = os.path.join(self.output_dir, "temp_background.mp4")
            if os.path.exists(temp_background):
                try:
                    os.remove(temp_background)
                except Exception:
                    pass
                    
            if os.path.exists(voiceover_path):
                try:
                    os.remove(voiceover_path)
                except Exception:
                    pass
                    
        return output_video_path

    async def compose(self, voiceover_text, background_video_path, output_filename="result_shorts.mp4"):
        """
        Coordinates the entire voiceover synthesis, transcription, srt generation, and video rendering.
        """
        voiceover_path = os.path.join(self.output_dir, "voiceover.wav")
        srt_path = os.path.join(self.output_dir, "subtitles.srt")
        output_video_path = os.path.join(self.output_dir, output_filename)

        # 1. Synthesize voiceover
        await self.generate_voiceover(voiceover_text, voiceover_path)

        # 2. Get precise timestamps via local transcription
        transcription_res = self.transcriber.transcribe(voiceover_path)

        # 3. Create highlighted SRT
        self.create_highlighted_srt(transcription_res, srt_path)

        # 4. Assemble final video
        self.assemble_video(background_video_path, voiceover_path, srt_path, output_video_path)

        return output_video_path

if __name__ == "__main__":
    # Test runner
    logging.basicConfig(level=logging.INFO)
    composer = VideoComposer()
