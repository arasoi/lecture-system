import argparse
import logging
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .calendar_lookup import find_class_for_timestamp, prime_graph_login
from .config import AppConfig, ensure_directories, load_config
from .notes import find_lecture_notes_template, generate_notes_with_ollama, write_markdown
from .transcribe import (
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    check_ffmpeg,
    extract_audio,
    get_working_audio_path,
    is_audio_file,
    is_video_file,
    transcribe_audio,
)
from .watch_folder import FileProcessorQueue, watch_directory, wait_for_file_stability

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingContext:
    created_time: datetime
    class_name: Optional[str] = None


def validate_environment(config: AppConfig) -> None:
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg is not installed or not available on PATH")

    if shutil.which("ollama") is None:
        raise RuntimeError("ollama is not installed or not available on PATH")

    if not config.source_dir.exists():
        raise RuntimeError(f"Source directory does not exist: {config.source_dir}")


def sanitize_filename(name: str) -> str:
    stem = Path(name).stem
    cleaned = re.sub(r"[^\w\-\. ]+", "", stem)
    cleaned = re.sub(r"[\s]+", "_", cleaned).strip("_.-")
    if not cleaned:
        cleaned = "lecture"
    return cleaned


def sanitize_path_segment(value: str, fallback: str = "lecture") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", value)
    cleaned = re.sub(r"[\s]+", " ", cleaned).strip(" .")
    return cleaned or fallback


def format_class_for_filename(value: str) -> str:
    cleaned = sanitize_path_segment(value)
    cleaned = re.sub(r"[^\w\-\. ]+", "", cleaned)
    cleaned = re.sub(r"[\s]+", "_", cleaned).strip("_.-")
    return (cleaned or "lecture").lower()


def parse_class_and_date(stem: str) -> Optional[tuple[str, str, Optional[str]]]:
    modern_match = re.match(
        r"^\s*(?P<class>.+?)_(?P<date>\d{2}-\d{2}-\d{4})_(?P<time>\d{1,2}\.\d{2}\.\d{2}(?:AM|PM))\s*$",
        stem,
        flags=re.IGNORECASE,
    )
    if modern_match:
        class_name = sanitize_path_segment(modern_match.group("class"))
        date_text = modern_match.group("date")
        time_text = modern_match.group("time").upper()
        return class_name, date_text, time_text

    legacy_match = re.match(
        r"^\s*(?P<class>.+?)\s*,\s*(?P<date>\d{2}\.\d{2}\.\d{4})(?:\s+(?P<time>\d{2}\.\d{2}))?\s*$",
        stem,
    )
    if not legacy_match:
        return None
    class_name = sanitize_path_segment(legacy_match.group("class"))
    date_text = legacy_match.group("date")
    time_text = legacy_match.group("time")
    return class_name, date_text, time_text


def recording_timestamp_from_filename(stem: str) -> Optional[datetime]:
    patterns = (
        (r"(?<!\d)(?P<ts>\d{4}-\d{2}-\d{2}[ _]\d{2}-\d{2}-\d{2})(?!\d)", ("%Y-%m-%d %H-%M-%S",)),
        (r"(?<!\d)(?P<ts>\d{4}-\d{2}-\d{2}[ _]\d{2}\.\d{2}\.\d{2})(?!\d)", ("%Y-%m-%d %H.%M.%S",)),
        (r"(?<!\d)(?P<ts>\d{8}[ _-]\d{6})(?!\d)", ("%Y%m%d %H%M%S",)),
        (r"(?<!\d)(?P<ts>\d{2}-\d{2}-\d{4}[ _]\d{2}-\d{2}-\d{2})(?!\d)", ("%m-%d-%Y %H-%M-%S",)),