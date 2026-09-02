"""
Persistent record of which recordings have already been turned into notes.

OneDrive uploads an in-progress recording in bursts, so the same lecture can land
in the source folder several times, each copy longer than the last. Every arrival
looks like a brand-new file, which previously produced one transcript and one note
per partial copy (``lecture.md``, ``lecture_1.md``, ``lecture_2.md``, ...), each
summarising a different-length prefix of the same class.

Recordings are keyed by the start timestamp in their filename, which stays the same
across partial copies. A copy that holds more audio than the one already processed
*supersedes* it: the transcript and note are rewritten rather than duplicated. A copy
that holds no more audio is already covered by what we have, so it is skipped.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .transcribe import probe_duration_seconds

logger = logging.getLogger(__name__)

STATE_VERSION = 1

EXTENT_DURATION = "duration"
EXTENT_SIZE = "size"

# A copy must hold at least this much more audio than the one already processed
# before it is worth transcribing again, so that re-encode jitter or a few trailing
# bytes do not trigger a pointless second pass over a full lecture.
GROWTH_TOLERANCE = 1.005


@dataclass(frozen=True)
class ProcessedRecording:
    """What was produced from the longest copy of a recording seen so far."""

    key: str
    extent: float
    extent_kind: str
    transcript_path: str
    note_path: str
    source_name: str
    processed_at: str
    archive_path: str = ""

    @property
    def transcript(self) -> Path:
        return Path(self.transcript_path)

    @property
    def note(self) -> Path:
        return Path(self.note_path)

    def is_superseded_by(self, extent: float, extent_kind: str) -> bool:
        """True when `extent` represents meaningfully more recording than this entry."""
        if extent_kind != self.extent_kind:
            # Seconds and bytes are not comparable. Reprocess rather than risk
            # discarding a copy that actually holds more of the lecture.
            return True
        return extent > self.extent * GROWTH_TOLERANCE


def recording_extent(path: Path) -> tuple[float, str]:
    """
    Measure how much recording a file holds.

    Prefers playable duration; falls back to byte size when ffprobe cannot read the
    file. Both grow monotonically as OneDrive syncs successively longer copies, so
    either works for comparing two copies of the same recording.
    """
    duration = probe_duration_seconds(path)
    if duration is not None:
        return duration, EXTENT_DURATION
    return float(path.stat().st_size), EXTENT_SIZE


def describe_extent(extent: float, extent_kind: str) -> str:
    """Human-readable form of an extent, for log messages."""
    if extent_kind == EXTENT_DURATION:
        return f"{extent / 60:.1f} min"
    return f"{extent / (1024 * 1024):.1f} MB"


class RecordingState:
    """A small JSON-backed map of recording key to what was produced from it."""

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, ProcessedRecording] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # A damaged state file must not stop lectures being processed; the worst
            # case of starting empty is that one recording gets a duplicate note.
            logger.warning("Could not read recording state at %s (%s); starting empty", self.path, exc)
            return

        for key, entry in (raw.get("recordings") or {}).items():
            try:
                self._entries[key] = ProcessedRecording(**entry)
            except TypeError:
                logger.warning("Ignoring malformed recording state entry %r in %s", key, self.path)

    def get(self, key: Optional[str]) -> Optional[ProcessedRecording]:
        if not key:
            return None
        return self._entries.get(key)

    def record(self, entry: ProcessedRecording) -> None:
        self._entries[entry.key] = entry
        self._save()

    def forget(self, key: str) -> None:
        if self._entries.pop(key, None) is not None:
            self._save()

    def _save(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "recordings": {key: asdict(entry) for key, entry in self._entries.items()},
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(temp_path, self.path)
        except OSError as exc:
            logger.error("Could not persist recording state to %s: %s", self.path, exc)
            temp_path.unlink(missing_ok=True)


def build_entry(
    key: str,
    extent: float,
    extent_kind: str,
    transcript_path: Path,
    note_path: Path,
    source_name: str,
    archive_path: Optional[Path] = None,
) -> ProcessedRecording:
    return ProcessedRecording(
        key=key,
        extent=extent,
        extent_kind=extent_kind,
        transcript_path=str(transcript_path),
        note_path=str(note_path),
        source_name=source_name,
        processed_at=datetime.now().isoformat(timespec="seconds"),
        archive_path=str(archive_path) if archive_path is not None else "",
    )
