import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

try:
    import torch
except ImportError:  # pragma: no cover - optional dependency
    torch = None

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".avi", ".webm"}

PROBE_TIMEOUT_SECONDS = 60


def subprocess_window_kwargs() -> dict[str, object]:
    """Keep child processes from flashing a console window on Windows."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def probe_duration_seconds(path: Path) -> Optional[float]:
    """
    Return the playable duration of a media file in seconds.

    Returns None when ffprobe is missing or cannot read the file, so callers can
    fall back to a coarser measure rather than failing the whole recording.
    """
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            **subprocess_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None

    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def extract_audio(input_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True, **subprocess_window_kwargs())
    return output_path


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def load_whisper_model(model_name: str, device: str = "cpu"):
    try:
        import whisper
    except ImportError as exc:
        raise ImportError(
            "The whisper package is required for transcription. Install it with `pip install -r requirements.txt`."
        ) from exc

    resolved_device = device
    if device == "cuda":
        cuda_available = False
        if torch is not None:
            try:
                cuda_available = torch.cuda.is_available()
            except Exception:
                cuda_available = False
        if not cuda_available:
            resolved_device = "cpu"

    return whisper.load_model(model_name, device=resolved_device)


def transcribe_audio(audio_path: Path, model_name: str = "base", device: str = "cpu") -> str:
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = load_whisper_model(model_name, device=device)
    result = model.transcribe(str(audio_path))
    text = result.get("text", "").strip()
    return text


def get_working_audio_path(source_path: Path, temp_dir: Path) -> Path:
    cleaned_name = source_path.stem.replace(" ", "_")
    return temp_dir / f"{cleaned_name}.wav"
