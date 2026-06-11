import os
import logging
import json

logger = logging.getLogger(__name__)

class Transcriber:
    def __init__(self, model_size="base", device="cpu", compute_type="int8"):
        """
        Initializes the faster-whisper transcriber.
        Model sizes: 'tiny', 'base', 'small', 'medium', 'large-v3'
        Devices: 'cpu', 'cuda'
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None

    def _lazy_init(self):
        if self.model is None:
            logger.info(f"Loading Whisper model '{self.model_size}' on '{self.device}'...")
            try:
                from faster_whisper import WhisperModel
                self.model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
                logger.info("Whisper model loaded successfully.")
            except ImportError:
                logger.error("faster-whisper is not installed. Please run pip install faster-whisper.")
                raise ImportError("faster-whisper not found")
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise e

    def transcribe(self, audio_path):
        """
        Transcribes the given audio file and returns a structured dict:
        {
            "text": "Full transcription...",
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.2,
                    "text": "Hello",
                    "words": [{"word": "Hello", "start": 0.0, "end": 0.5}, ...]
                },
                ...
            ]
        }
        """
        self._lazy_init()
        logger.info(f"Transcribing audio file: {audio_path}")
        
        try:
            segments, info = self.model.transcribe(audio_path, word_timestamps=True)
            logger.info(f"Detected language: {info.language} with probability {info.language_probability:.2f}")
            
            result_segments = []
            full_text = []
            
            for segment in segments:
                words_list = []
                if segment.words:
                    for w in segment.words:
                        words_list.append({
                            "word": w.word,
                            "start": w.start,
                            "end": w.end,
                            "probability": w.probability
                        })
                
                result_segments.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "words": words_list
                })
                full_text.append(segment.text)
                
            return {
                "language": info.language,
                "text": " ".join(full_text),
                "segments": result_segments
            }
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            raise e

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Simple self-test
    transcriber = Transcriber(model_size="tiny")
    # You would pass a valid wav path here
    # transcriber.transcribe("path_to_audio.wav")
