import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".avi", ".webm"}


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def extract_audio(video_path: Path, audio_path: Path) -> None:
    """Extract audio from video using ffmpeg."""
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-q:a", "9", "-n", str(audio_path)],
        check=True,
        capture_output=True,
    )


def get_working_audio_path(recording_path: Path, temp_dir: Path) -> Path:
    """Get the path to use for audio processing."""
    if is_audio_file(recording_path):
        return recording_path
    # For video files, extract audio
    audio_path = temp_dir / f"{recording_path.stem}.wav"
    if not audio_path.exists():
        extract_audio(recording_path, audio_path)
    return audio_path


def transcribe_audio(audio_path: Path, model: str = "base", device: str = "cpu") -> str:
    """Transcribe audio using Whisper."""
    import whisper
    
    whisper_model = whisper.load_model(model, device=device)
    result = whisper_model.transcribe(str(audio_path))
    return result["text"]
