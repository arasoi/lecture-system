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
        (r"(?<!\d)(?P<ts>\d{2}\.\d{2}\.\d{4}[ _]\d{2}\.\d{2}\.\d{2})(?!\d)", ("%m.%d.%Y %H.%M.%S",)),
        (r"(?<!\d)(?P<ts>\d{2}-\d{2}-\d{4}[ _]\d{1,2}\.\d{2}\.\d{2}(?:AM|PM))(?!\d)", ("%m-%d-%Y %I.%M.%S%p",)),
        (r"(?<!\d)(?P<ts>\d{4}-\d{2}-\d{2}[ _]\d{1,2}\.\d{2}\.\d{2}(?:AM|PM))(?!\d)", ("%Y-%m-%d %I.%M.%S%p",)),
    )
    for pattern, formats in patterns:
        match = re.search(pattern, stem, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group("ts").replace("_", " ")
        for dt_format in formats:
            try:
                return datetime.strptime(candidate, dt_format)
            except ValueError:
                continue
    return None


def recording_timestamp_from_file_metadata(path: Path) -> datetime:
    """
    Get the recording timestamp from file metadata.

    Note: On Windows with OneDrive/copied files, st_ctime gets updated to copy time,
    but st_mtime preserves the original recording time.
    """
    stats = path.stat()
    timestamp = stats.st_mtime
    return datetime.fromtimestamp(timestamp)


def resolve_recording_context(path: Path, config: AppConfig) -> RecordingContext:
    meta_time = recording_timestamp_from_file_metadata(path)
    # Filename timestamp is preferred when available: it encodes the exact recording start
    # time and is unaffected by OneDrive sync, file copies, or processing delays.
    filename_time = recording_timestamp_from_filename(path.stem)
    lookup_time = filename_time if filename_time else meta_time

    logger.info(
        "Recording %s: filename_time=%s, file_metadata_time=%s, using=%s",
        path.name,
        filename_time.strftime("%Y-%m-%d %H:%M:%S") if filename_time else "N/A",
        meta_time.strftime("%Y-%m-%d %H:%M:%S"),
        lookup_time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    if not config.calendar_rename.enabled:
        logger.debug("Calendar rename disabled; no class lookup will be performed")
        return RecordingContext(created_time=lookup_time, class_name=None)

    provider = getattr(config.calendar_rename, "provider", "unknown")
    logger.info(
        "Looking up calendar event for %s using provider=%s, lookback=%d min, lookahead=%d min",
        lookup_time.strftime("%Y-%m-%d %H:%M:%S"),
        provider,
        config.calendar_rename.lookback_minutes,
        config.calendar_rename.lookahead_minutes,
    )

    try:
        class_name = find_class_for_timestamp(
            lookup_time,
            config=config.calendar_rename,
            lookback_minutes=config.calendar_rename.lookback_minutes,
            lookahead_minutes=config.calendar_rename.lookahead_minutes,
        )
    except RuntimeError as exc:
        logger.error("Calendar-based class lookup failed for %s: %s", path.name, exc)
        return RecordingContext(created_time=lookup_time, class_name=None)

    if class_name:
        logger.info(
            "Resolved class '%s' for recording %s (lookup time: %s)",
            class_name, path.name, lookup_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return RecordingContext(created_time=lookup_time, class_name=class_name)

    # Fallback: if filename time was used but didn't match, try file metadata time
    if filename_time and meta_time != filename_time:
        logger.warning(
            "No class found using filename time %s for %s; trying file metadata time %s...",
            filename_time.strftime("%Y-%m-%d %H:%M:%S"), path.name, meta_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        try:
            class_name = find_class_for_timestamp(
                meta_time,
                config=config.calendar_rename,
                lookback_minutes=config.calendar_rename.lookback_minutes,
                lookahead_minutes=config.calendar_rename.lookahead_minutes,
            )
            if class_name:
                logger.info(
                    "Resolved class '%s' for recording %s using file metadata time %s",
                    class_name, path.name, meta_time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                return RecordingContext(created_time=filename_time, class_name=class_name)
        except RuntimeError as exc:
            logger.debug("File metadata fallback lookup also failed: %s", exc)

    logger.warning("No calendar event found for %s using either filename or file metadata time", path.name)
    return RecordingContext(created_time=lookup_time, class_name=None)


def rename_file_for_calendar(path: Path, context: RecordingContext) -> Path:
    if parse_class_and_date(path.stem):
        logger.debug("File %s already matches calendar naming pattern; no rename needed", path.name)
        return path

    if not context.class_name:
        logger.debug("No class resolved for %s; keeping original filename", path.name)
        return path

    safe_class_name = format_class_for_filename(context.class_name)
    date_text = context.created_time.strftime("%m-%d-%Y")
    time_text = context.created_time.strftime("%I.%M.%S%p").lstrip("0")
    renamed = path.with_name(f"{safe_class_name}_{date_text}_{time_text}{path.suffix.lower()}")

    if renamed == path:
        logger.debug("Computed filename matches original; no rename needed: %s", path.name)
        return path

    index = 1
    while renamed.exists():
        logger.debug("Target filename exists; trying index %d: %s", index, renamed.name)
        renamed = path.with_name(f"{safe_class_name}_{date_text}_{time_text}_{index}{path.suffix.lower()}")
        index += 1

    logger.info("Renaming %s \u2192 %s (class: %s, created: %s)",
                path.name, renamed.name, context.class_name,
                context.created_time.strftime("%Y-%m-%d %H:%M:%S"))
    path = path.replace(renamed)
    return path


def get_output_paths(source_path: Path, config: AppConfig, context: Optional[RecordingContext] = None) -> tuple[Path, Path]:
    stem = sanitize_filename(source_path.name)
    transcript_path = config.transcript_dir / f"{stem}.txt"

    if context is not None and context.class_name:
        class_name = sanitize_path_segment(context.class_name)
        class_prefix = format_class_for_filename(class_name)
        date_text = context.created_time.strftime("%m-%d-%Y")
        time_text = context.created_time.strftime("%I.%M.%S%p").lstrip("0")
        prefixed_stem = f"{class_prefix}_{date_text}_{time_text}"
        transcript_path = config.transcript_dir / f"{prefixed_stem}.txt"
        note_path = config.obsidian_vault_dir / class_name / f"{prefixed_stem}.md"
        logger.info("Output paths (from context): transcript=%s, note=%s", transcript_path, note_path)
        return transcript_path, note_path

    parsed = parse_class_and_date(source_path.stem)
    if parsed:
        class_name, date_text, time_text = parsed
        class_prefix = format_class_for_filename(class_name)
        base_stem = f"{date_text}_{time_text}" if time_text else date_text
        prefixed_stem = f"{class_prefix}_{base_stem}"
        transcript_path = config.transcript_dir / f"{prefixed_stem}.txt"
        note_path = config.obsidian_vault_dir / class_name / f"{prefixed_stem}.md"
        logger.info("Output paths (from filename): transcript=%s, note=%s", transcript_path, note_path)
        return transcript_path, note_path

    note_path = config.obsidian_vault_dir / "unknown_class" / f"{stem}.md"
    logger.warning("Output paths (unknown class): transcript=%s, note=%s", transcript_path, note_path)
    return transcript_path, note_path


def ensure_unique_output_paths(transcript_path: Path, note_path: Path) -> tuple[Path, Path]:
    if not transcript_path.exists() and not note_path.exists():
        return transcript_path, note_path

    index = 1
    while True:
        transcript_candidate = transcript_path.with_name(f"{transcript_path.stem}_{index}{transcript_path.suffix}")
        note_candidate = note_path.with_name(f"{note_path.stem}_{index}{note_path.suffix}")
        if not transcript_candidate.exists() and not note_candidate.exists():
            return transcript_candidate, note_candidate
        index += 1


def reclassify_unknown_notes(config: AppConfig) -> None:
    unknown_dir = config.obsidian_vault_dir / "unknown_class"
    if not unknown_dir.exists():
        return

    moved_count = 0
    for note_path in sorted(unknown_dir.glob("*.md")):
        timestamp = recording_timestamp_from_filename(note_path.stem)
        if timestamp is None:
            continue
        try:
            class_name = find_class_for_timestamp(
                timestamp,
                config=config.calendar_rename,
                lookback_minutes=config.calendar_rename.lookback_minutes,
                lookahead_minutes=config.calendar_rename.lookahead_minutes,
            )
        except RuntimeError as exc:
            logger.warning("Calendar lookup unavailable while reclassifying %s: %s", note_path, exc)
            return
        if not class_name:
            continue

        class_dir = config.obsidian_vault_dir / format_class_for_filename(class_name)
        class_dir.mkdir(parents=True, exist_ok=True)
        class_prefix = format_class_for_filename(class_name)

        # Build canonical name from the parsed timestamp so the note is named correctly
        # regardless of what the original filename looked like (raw timestamp, _1 suffix, etc.)
        date_text = timestamp.strftime("%m-%d-%Y")
        time_text = timestamp.strftime("%I.%M.%S%p").lstrip("0")
        canonical_stem = f"{class_prefix}_{date_text}_{time_text}"
        destination = class_dir / f"{canonical_stem}.md"

        index = 1
        while destination.exists():
            destination = class_dir / f"{canonical_stem}_{index}.md"
            index += 1
        note_path.replace(destination)
        moved_count += 1
        logger.info("Reclassified %s -> %s/%s", note_path.name, class_name, destination.name)

    if moved_count:
        logger.info("Reclassified %d note(s) from unknown_class", moved_count)


def move_file_to_target(source_path: Path, target_dir: Optional[Path]) -> Path:
    if target_dir is None:
        return source_path

    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / source_path.name
    index = 1
    while destination.exists():
        destination = target_dir / f"{source_path.stem}_{index}{source_path.suffix}"
        index += 1

    try:
        return source_path.replace(destination)
    except OSError:
        shutil.copy2(source_path, destination)
        source_path.unlink(missing_ok=True)
        return destination


def should_process(path: Path) -> bool:
    if path.name.startswith("~") or path.name.startswith("."):
        return False
    return is_audio_file(path) or is_video_file(path)


def process_file(path: Path, config: AppConfig, force: bool = False) -> None:
    if not should_process(path):
        logger.debug("Skipping unsupported file %s", path)
        return

    if not path.exists():
        logger.warning("File disappeared before processing: %s", path)
        return

    audio_path = path
    try:
        if not wait_for_file_stability(path):
            logger.warning("File did not stabilize: %s", path)
            return

        recording_context = resolve_recording_context(path, config)
        path = rename_file_for_calendar(path, recording_context)

        transcript_path, note_path = get_output_paths(path, config, context=recording_context)
        if not force:
            transcript_path, note_path = ensure_unique_output_paths(transcript_path, note_path)

        logger.info("Processing %s", path)

        if is_video_file(path):
            audio_path = get_working_audio_path(path, config.temp_dir)
            extract_audio(path, audio_path)
            logger.info("Extracted audio to %s", audio_path)

        transcript_text = transcribe_audio(
            audio_path,
            model_name=config.transcription.model,
            device=config.transcription.device,
        )
        if not transcript_text.strip():
            logger.warning("Transcript was empty for %s", path)

        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(transcript_text.strip() + "\n", encoding="utf-8")
        logger.info("Saved transcript to %s", transcript_path)

        notes_text = generate_notes_with_ollama(
            transcript_text,
            model_name=config.ollama.model,
            prompt_template=config.ollama.prompt_template,
        )
        template_path = find_lecture_notes_template(config.obsidian_vault_dir)
        if template_path is None:
            raise RuntimeError(
                "Lecture notes template not found. Expected LectureNotesTemplate in ObsidianVault\\templates."
            )
        template_text = template_path.read_text(encoding="utf-8")
        write_markdown(notes_text, note_path, template_text=template_text)
        logger.info("Saved lecture notes to %s", note_path)

        if config.archive_dir is not None:
            moved = move_file_to_target(path, config.archive_dir)
            logger.info("Moved processed file to %s", moved)
    except Exception:
        logger.exception("Failed to process %s", path)
        if config.error_dir is not None:
            moved = move_file_to_target(path, config.error_dir)
            logger.info("Moved failed file to %s", moved)
    finally:
        if audio_path != path and audio_path.exists():
            try:
                audio_path.unlink()
            except Exception:
                logger.debug("Could not remove temporary audio file %s", audio_path)


def enqueue_existing_files(config: AppConfig, queue: FileProcessorQueue) -> None:
    for path in sorted(config.source_dir.iterdir()):
        if path.is_file() and should_process(path):
            queue.enqueue(path)


def prompt_value(prompt_text: str, default: Optional[str] = None) -> str:
    if default:
        text = input(f"{prompt_text} [{default}]: ").strip()
        return text or default
    return input(f"{prompt_text}: ").strip()


def generate_config(path: Path) -> int:
    if path.exists():
        answer = input(f"{path} already exists. Overwrite? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborting config generation.")
            return 1

    print("Generating config.yaml for the lecture transcription watcher.")
    home = Path.home()
    source_dir = prompt_value("OneDrive recordings source folder", str(home / "OneDrive/Lectures"))
    obsidian_vault_dir = prompt_value("Obsidian vault notes folder", str(home / "ObsidianVault/Lecture Notes"))
    temp_dir = prompt_value("Temporary working folder", str(home / ".lecture_transcriber/temp"))
    transcript_dir = prompt_value("Transcript output folder", str(home / ".lecture_transcriber/transcripts"))
    archive_dir = prompt_value("Archive folder for processed recordings", str(home / ".lecture_transcriber/processed"))
    error_dir = prompt_value("Error folder for failed recordings", str(home / ".lecture_transcriber/errors"))
    calendar_rename_enabled = prompt_value("Rename files from calendar metadata (true/false)", "true")
    calendar_provider = prompt_value("Calendar provider (auto/graph/outlook)", "auto")
    graph_auth_mode = prompt_value("Graph auth mode (device_code/client_credentials)", "device_code")
    calendar_rename_lookback = prompt_value("Calendar lookup lookback minutes", "180")
    calendar_rename_lookahead = prompt_value("Calendar lookup lookahead minutes", "180")
    graph_tenant_id = prompt_value("Microsoft Graph tenant ID", "")
    graph_client_id = prompt_value("Microsoft Graph client ID", "")
    graph_client_secret = prompt_value("Microsoft Graph client secret", "")
    graph_mailbox_user = prompt_value("Microsoft Graph mailbox user (UPN/email)", "")
    graph_token_cache_path = prompt_value("Microsoft Graph token cache file path", str(home / ".lecture_transcriber/graph_token_cache.json"))
    whisper_model = prompt_value("Whisper model name", "base")
    device = prompt_value("Transcription device (cpu/cuda)", "cpu")
    ollama_model = prompt_value("Ollama model name", "llama3")

    config_data = {
        "source_dir": source_dir,
        "obsidian_vault_dir": obsidian_vault_dir,
        "temp_dir": temp_dir,
        "transcript_dir": transcript_dir,
        "archive_dir": archive_dir,
        "error_dir": error_dir,
        "calendar_rename": {
            "enabled": calendar_rename_enabled.lower() in {"true", "yes", "1"},
            "provider": calendar_provider,
            "graph_auth_mode": graph_auth_mode,
            "lookback_minutes": int(calendar_rename_lookback),
            "lookahead_minutes": int(calendar_rename_lookahead),
            "graph_tenant_id": graph_tenant_id,
            "graph_client_id": graph_client_id,
            "graph_client_secret": graph_client_secret,
            "graph_mailbox_user": graph_mailbox_user,
            "graph_token_cache_path": graph_token_cache_path,
        },
        "transcription": {
            "model": whisper_model,
            "device": device,
        },
        "ollama": {
            "model": ollama_model,
        },
    }

    path.write_text(yaml.dump(config_data, default_flow_style=False), encoding="utf-8")
    print(f"Config written to {path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lecture transcription watcher")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--once", action="store_true", help="Process existing files and exit")
    parser.add_argument("--force", action="store_true", help="Re-process files that already have output")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--generate-config", action="store_true", help="Generate a config file interactively")
    parser.add_argument("--graph-login", action="store_true", help="Authenticate with Microsoft Graph (device-code flow)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    config_path = Path(args.config)
    if args.generate_config:
        return generate_config(config_path)

    if not config_path.exists():
        logger.error("Configuration file not found: %s", config_path)
        return 2

    config = load_config(config_path)
    if args.graph_login:
        try:
            prime_graph_login(config.calendar_rename)
        except RuntimeError as exc:
            logger.error(exc)
            return 4
        logger.info("Microsoft Graph device-code login completed.")
        return 0
    ensure_directories(config)
    reclassify_unknown_notes(config)

    try:
        validate_environment(config)
    except Exception as exc:
        logger.error(exc)
        return 3

    processor = FileProcessorQueue(lambda path: process_file(path, config, force=args.force))
    enqueue_existing_files(config, processor)

    if args.once:
        processor.queue.join()
        return 0

    supported_extensions = AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS)
    observer = watch_directory(config.source_dir, processor.enqueue, supported_extensions=supported_extensions)

    logger.info("Watching %s for new lecture files...", config.source_dir)
    try:
        while True:
            args = None
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher")
    finally:
        observer.stop()
        observer.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
