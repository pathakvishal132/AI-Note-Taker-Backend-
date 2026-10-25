"""Transcription service using faster-whisper."""
import logging
import tempfile
import os
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model = None


class TranscriptionError(Exception):
    """Raised when transcription fails."""
    pass


class TranscriptionService:
    """Speech-to-text service using faster-whisper.

    The model is loaded lazily on first use and cached as a singleton.
    Thread-safe model loading via a lock.
    """

    @staticmethod
    def _get_model():
        """Get or lazily load the faster-whisper model (singleton)."""
        global _model
        if _model is not None:
            return _model

        with _model_lock:
            # Double-check after acquiring lock
            if _model is not None:
                return _model

            model_size = getattr(settings, 'STT_MODEL_SIZE', 'base')
            device = getattr(settings, 'STT_DEVICE', 'cpu')
            compute_type = getattr(settings, 'STT_COMPUTE_TYPE', 'int8')

            logger.info(
                f"Loading faster-whisper model: size={model_size}, "
                f"device={device}, compute_type={compute_type}"
            )
            try:
                from faster_whisper import WhisperModel
                _model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type=compute_type,
                )
                logger.info("faster-whisper model loaded successfully")
                return _model
            except Exception as e:
                logger.error(f"Failed to load faster-whisper model: {e}")
                raise TranscriptionError(
                    f"Failed to load speech recognition model: {e}"
                ) from e

    @staticmethod
    def is_model_loaded() -> bool:
        """Check if the model is currently loaded."""
        return _model is not None

    @classmethod
    def transcribe(cls, audio_file) -> str:
        """Transcribe an audio file to text.

        Args:
            audio_file: A Django UploadedFile or file-like object.

        Returns:
            The transcribed text as a string.

        Raises:
            TranscriptionError: If transcription fails.
        """
        model = cls._get_model()

        # Write uploaded file to a temp file for faster-whisper
        suffix = '.webm'
        if hasattr(audio_file, 'name'):
            _, ext = os.path.splitext(audio_file.name)
            if ext:
                suffix = ext

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
                for chunk in audio_file.chunks() if hasattr(audio_file, 'chunks') else [audio_file.read()]:
                    tmp.write(chunk)

            logger.debug(f"Transcribing audio file: {tmp_path}")
            segments, info = model.transcribe(
                tmp_path,
                language='en',
                beam_size=5,
                vad_filter=True,
            )

            # Collect all segments into text
            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text.strip())

            transcript = ' '.join(transcript_parts).strip()

            if not transcript:
                raise TranscriptionError("Transcription produced empty text")

            logger.info(
                f"Transcription complete: {len(transcript)} chars, "
                f"language={info.language}, probability={info.language_probability:.2f}"
            )
            return transcript

        except TranscriptionError:
            raise
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptionError(f"Failed to transcribe audio: {e}") from e
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
