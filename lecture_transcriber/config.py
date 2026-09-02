from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_STATE_FILENAME = "processed_recordings.json"


def default_state_path() -> Path:
    return Path.home() / ".lecture_transcriber" / DEFAULT_STATE_FILENAME


@dataclass
class TranscriptionConfig:
    model: str = "base"
    backend: str = "whisper"
    device: str = "cpu"


@dataclass
class OllamaConfig:
    model: str = "llama2"
    prompt_template: str = (
        "You are a lecture notes assistant. Summarize the following transcript into Obsidian-compatible "
        "Markdown notes with headings, bullet points, definitions, and examples.\n\n"
        "Transcript:\n{transcript}"
    )


@dataclass
class AppConfig:
    source_dir: Path
    obsidian_vault_dir: Path
    temp_dir: Path
    transcript_dir: Path
    transcription: TranscriptionConfig
    ollama: OllamaConfig
    archive_dir: Optional[Path] = None
    error_dir: Optional[Path] = None
    calendar_rename: "CalendarRenameConfig" = None
    # Tracks which recordings have already been processed, so a longer copy of a
    # recording replaces its notes instead of creating a second set.
    state_path: Path = None
    # How long a recording must sit untouched before it is treated as finished, so that
    # a recording still being synced is not processed while incomplete. 0 disables.
    quiet_period_minutes: int = 20


@dataclass
class CalendarRenameConfig:
    enabled: bool = False
    provider: str = "auto"
    lookback_minutes: int = 180
    lookahead_minutes: int = 180
    graph_auth_mode: str = "device_code"
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_mailbox_user: str = ""
    graph_token_cache_path: str = ""


def load_config(path: Path) -> AppConfig:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if raw is None:
        raise ValueError(f"Configuration file {path} is empty")

    source_dir = Path(raw.get("source_dir", "")).expanduser()
    obsidian_vault_dir = Path(raw.get("obsidian_vault_dir", "")).expanduser()
    temp_dir = Path(raw.get("temp_dir", "")).expanduser()
    transcript_dir = Path(raw.get("transcript_dir", "")).expanduser()
    archive_dir = raw.get("archive_dir")
    error_dir = raw.get("error_dir")
    state_path = raw.get("state_path")

    transcription_raw = raw.get("transcription", {}) or {}
    ollama_raw = raw.get("ollama", {}) or {}
    calendar_rename_raw = raw.get("calendar_rename", {}) or {}

    transcription = TranscriptionConfig(
        model=transcription_raw.get("model", "base"),
        backend=transcription_raw.get("backend", "whisper"),
        device=transcription_raw.get("device", "cpu"),
    )
    ollama = OllamaConfig(
        model=ollama_raw.get("model", "llama2"),
        prompt_template=ollama_raw.get("prompt_template", OllamaConfig().prompt_template),
    )
    calendar_rename = CalendarRenameConfig(
        enabled=bool(calendar_rename_raw.get("enabled", False)),
        provider=str(calendar_rename_raw.get("provider", "auto")).strip().lower(),
        lookback_minutes=int(calendar_rename_raw.get("lookback_minutes", 180)),
        lookahead_minutes=int(calendar_rename_raw.get("lookahead_minutes", 180)),
        graph_auth_mode=str(calendar_rename_raw.get("graph_auth_mode", "device_code")).strip().lower(),
        graph_tenant_id=str(calendar_rename_raw.get("graph_tenant_id", "")).strip(),
        graph_client_id=str(calendar_rename_raw.get("graph_client_id", "")).strip(),
        graph_client_secret=str(calendar_rename_raw.get("graph_client_secret", "")).strip(),
        graph_mailbox_user=str(calendar_rename_raw.get("graph_mailbox_user", "")).strip(),
        graph_token_cache_path=str(calendar_rename_raw.get("graph_token_cache_path", "")).strip(),
    )

    return AppConfig(
        source_dir=source_dir,
        obsidian_vault_dir=obsidian_vault_dir,
        temp_dir=temp_dir,
        transcript_dir=transcript_dir,
        archive_dir=Path(archive_dir).expanduser() if archive_dir is not None else None,
        error_dir=Path(error_dir).expanduser() if error_dir is not None else None,
        transcription=transcription,
        ollama=ollama,
        calendar_rename=calendar_rename,
        state_path=Path(state_path).expanduser() if state_path else default_state_path(),
        quiet_period_minutes=int(raw.get("quiet_period_minutes", 20)),
    )


def ensure_directories(config: AppConfig) -> None:
    config.source_dir.mkdir(parents=True, exist_ok=True)
    config.obsidian_vault_dir.mkdir(parents=True, exist_ok=True)
    config.temp_dir.mkdir(parents=True, exist_ok=True)
    config.transcript_dir.mkdir(parents=True, exist_ok=True)
    if config.archive_dir is not None:
        config.archive_dir.mkdir(parents=True, exist_ok=True)
    if config.error_dir is not None:
        config.error_dir.mkdir(parents=True, exist_ok=True)
    if config.state_path is not None:
        config.state_path.parent.mkdir(parents=True, exist_ok=True)
