import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lecture_transcriber.main import (
    process_file,
    recording_key,
)
from lecture_transcriber.state import (
    EXTENT_DURATION,
    EXTENT_SIZE,
    ProcessedRecording,
    RecordingState,
    build_entry,
    describe_extent,
)


def make_entry(**overrides) -> ProcessedRecording:
    defaults = dict(
        key="20260804T092247",
        extent=151.6,
        extent_kind=EXTENT_DURATION,
        transcript_path=r"D:\transcripts\univ103_08-04-2026_9.22.47AM.txt",
        note_path=r"D:\vault\univ103\univ103_08-04-2026_9.22.47AM.md",
        source_name="univ103_08-04-2026_9.22.47AM.mp3",
        processed_at="2026-08-04T09:33:51",
    )
    defaults.update(overrides)
    return ProcessedRecording(**defaults)


class RecordingKeyTests(unittest.TestCase):
    def test_partial_copies_of_one_recording_share_a_key(self):
        # OneDrive delivers each partial under the same name; after calendar rename the
        # class prefix is attached but the start timestamp is unchanged.
        keys = {
            recording_key(Path(r"C:\incoming\2026-08-04 09.22.47.mp3")),
            recording_key(Path(r"C:\incoming\univ103-ames_08-04-2026_9.22.47AM.mp3")),
        }
        self.assertEqual(keys, {"20260804T092247"})

    def test_distinct_recordings_get_distinct_keys(self):
        self.assertNotEqual(
            recording_key(Path(r"C:\incoming\2026-08-04 09.22.47.mp3")),
            recording_key(Path(r"C:\incoming\2026-08-03 09.20.57.mp3")),
        )

    def test_returns_none_when_filename_has_no_timestamp(self):
        self.assertIsNone(recording_key(Path(r"C:\incoming\random_capture.m4a")))


class SupersedeTests(unittest.TestCase):
    def test_longer_copy_supersedes(self):
        self.assertTrue(make_entry(extent=151.6).is_superseded_by(773.5, EXTENT_DURATION))

    def test_identical_copy_does_not_supersede(self):
        self.assertFalse(make_entry(extent=773.5).is_superseded_by(773.5, EXTENT_DURATION))

    def test_shorter_copy_does_not_supersede(self):
        self.assertFalse(make_entry(extent=2946.0).is_superseded_by(151.6, EXTENT_DURATION))

    def test_trivial_growth_does_not_supersede(self):
        # Re-encode jitter must not trigger another full transcription pass.
        self.assertFalse(make_entry(extent=2946.0).is_superseded_by(2947.0, EXTENT_DURATION))

    def test_incomparable_units_supersede_rather_than_drop_audio(self):
        self.assertTrue(make_entry(extent=151.6, extent_kind=EXTENT_DURATION).is_superseded_by(90.0, EXTENT_SIZE))


class RecordingStateTests(unittest.TestCase):
    def test_round_trips_entries_through_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "nested" / "processed_recordings.json"
            RecordingState(path).record(make_entry())

            reloaded = RecordingState(path).get("20260804T092247")
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.extent, 151.6)
            self.assertEqual(reloaded.note.name, "univ103_08-04-2026_9.22.47AM.md")

    def test_unknown_and_empty_keys_return_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = RecordingState(Path(temp_dir) / "state.json")
            self.assertIsNone(state.get("nope"))
            self.assertIsNone(state.get(None))

    def test_corrupt_state_file_starts_empty_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(RecordingState(path).get("20260804T092247"))

    def test_entry_missing_newer_fields_still_loads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            path.write_text(
                '{"version": 1, "recordings": {"k": {"key": "k", "extent": 1.0, '
                '"extent_kind": "duration", "transcript_path": "t.txt", "note_path": "n.md", '
                '"source_name": "s.mp3", "processed_at": "2026-08-04T09:33:51"}}}',
                encoding="utf-8",
            )
            entry = RecordingState(path).get("k")
            self.assertIsNotNone(entry)
            self.assertEqual(entry.archive_path, "")

    def test_forget_removes_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            state = RecordingState(path)
            state.record(make_entry())
            state.forget("20260804T092247")
            self.assertIsNone(RecordingState(path).get("20260804T092247"))


class DescribeExtentTests(unittest.TestCase):
    def test_formats_duration_as_minutes(self):
        self.assertEqual(describe_extent(2946.0, EXTENT_DURATION), "49.1 min")

    def test_formats_size_as_megabytes(self):
        self.assertEqual(describe_extent(45.22 * 1024 * 1024, EXTENT_SIZE), "45.2 MB")


class ProcessFileStateTests(unittest.TestCase):
    """End-to-end behaviour for the partial-sync case that produced duplicate notes."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.source_dir = self.root / "incoming"
        self.source_dir.mkdir()
        self.archive_dir = self.root / "archive"
        self.vault = self.root / "vault"
        (self.vault / "templates").mkdir(parents=True)
        (self.vault / "templates" / "LectureNotesTemplate.md").write_text(
            "---\nClass Name:\nProfessor:\nBuilding:\nDate:\nTime:\n---\n", encoding="utf-8"
        )
        self.config = SimpleNamespace(
            temp_dir=self.root / "temp",
            transcription=SimpleNamespace(model="base", device="cpu"),
            ollama=SimpleNamespace(model="llama2", prompt_template="{transcript}"),
            archive_dir=self.archive_dir,
            error_dir=self.root / "errors",
            obsidian_vault_dir=self.vault,
            transcript_dir=self.root / "transcripts",
            calendar_rename=SimpleNamespace(enabled=False, lookback_minutes=180, lookahead_minutes=180),
            quiet_period_minutes=0,
        )
        self.state = RecordingState(self.root / "state.json")

    def tearDown(self):
        self._temp.cleanup()

    def run_partial(self, duration: float, transcript: str, notes: str) -> None:
        """Simulate OneDrive landing a copy of the same recording holding `duration` seconds."""
        source = self.source_dir / "2026-08-04 09.22.47.mp3"
        source.write_text("audio" * int(duration), encoding="utf-8")
        with (
            patch("lecture_transcriber.main.wait_for_file_stability", return_value=True),
            patch("lecture_transcriber.main.recording_extent", return_value=(duration, EXTENT_DURATION)),
            patch("lecture_transcriber.main.transcribe_audio", return_value=transcript),
            patch("lecture_transcriber.main.generate_notes_with_ollama", return_value=notes),
        ):
            process_file(source, self.config, force=False, state=self.state)

    def note_files(self) -> list[str]:
        return sorted(p.name for p in (self.vault / "unknown_class").glob("*.md"))

    def transcript_files(self) -> list[str]:
        return sorted(p.name for p in self.config.transcript_dir.glob("*.txt"))

    def test_successive_partials_produce_one_note_holding_the_longest_pass(self):
        self.run_partial(151.6, "first 2 minutes", "# Notes from 2 minutes")
        self.run_partial(773.5, "first 13 minutes", "# Notes from 13 minutes")
        self.run_partial(2946.0, "the whole lecture", "# Notes from the whole lecture")

        self.assertEqual(self.note_files(), ["2026-08-04_09.22.47.md"])
        self.assertEqual(self.transcript_files(), ["2026-08-04_09.22.47.txt"])

        note = (self.vault / "unknown_class" / "2026-08-04_09.22.47.md").read_text(encoding="utf-8")
        self.assertIn("Notes from the whole lecture", note)
        self.assertNotIn("Notes from 2 minutes", note)

    def test_shorter_copy_arriving_late_is_skipped_and_parked_in_partials(self):
        self.run_partial(2946.0, "the whole lecture", "# Notes from the whole lecture")
        self.run_partial(151.6, "first 2 minutes", "# Notes from 2 minutes")

        note = (self.vault / "unknown_class" / "2026-08-04_09.22.47.md").read_text(encoding="utf-8")
        self.assertIn("Notes from the whole lecture", note)
        self.assertEqual(len(list((self.archive_dir / "partials").glob("*.mp3"))), 1)

    def test_archive_root_keeps_one_file_per_recording(self):
        self.run_partial(151.6, "first 2 minutes", "# Notes from 2 minutes")
        self.run_partial(773.5, "first 13 minutes", "# Notes from 13 minutes")
        self.run_partial(2946.0, "the whole lecture", "# Notes from the whole lecture")

        self.assertEqual(len(list(self.archive_dir.glob("*.mp3"))), 1)
        self.assertEqual(len(list((self.archive_dir / "partials").glob("*.mp3"))), 2)

    def test_without_state_the_duplicates_still_appear(self):
        """Guards the diagnosis: unchanged behaviour when tracking is unavailable."""
        self.run_partial(151.6, "first 2 minutes", "# Notes from 2 minutes")
        self.state = None
        self.run_partial(773.5, "first 13 minutes", "# Notes from 13 minutes")

        self.assertEqual(
            self.note_files(),
            ["2026-08-04_09.22.47.md", "2026-08-04_09.22.47_1.md"],
        )

    def test_recording_still_syncing_is_deferred_without_transcribing(self):
        self.config.quiet_period_minutes = 20
        source = self.source_dir / "2026-08-04 09.22.47.mp3"
        source.write_text("audio", encoding="utf-8")
        with (
            patch("lecture_transcriber.main.wait_for_file_stability", return_value=True),
            patch("lecture_transcriber.main.transcribe_audio") as transcribe,
        ):
            process_file(source, self.config, force=False, state=self.state)

        transcribe.assert_not_called()
        # Left in place so a later pass picks it up once the recording is finished.
        self.assertTrue(source.exists())
        self.assertEqual(self.note_files(), [])

    def test_force_bypasses_the_quiet_period(self):
        self.config.quiet_period_minutes = 20
        source = self.source_dir / "2026-08-04 09.22.47.mp3"
        source.write_text("audio", encoding="utf-8")
        with (
            patch("lecture_transcriber.main.wait_for_file_stability", return_value=True),
            patch("lecture_transcriber.main.recording_extent", return_value=(2946.0, EXTENT_DURATION)),
            patch("lecture_transcriber.main.transcribe_audio", return_value="text") as transcribe,
            patch("lecture_transcriber.main.generate_notes_with_ollama", return_value="# Notes"),
        ):
            process_file(source, self.config, force=True, state=self.state)

        transcribe.assert_called_once()

    def test_recording_without_filename_timestamp_is_not_tracked(self):
        source = self.source_dir / "random_capture.m4a"
        source.write_text("audio", encoding="utf-8")
        with (
            patch("lecture_transcriber.main.wait_for_file_stability", return_value=True),
            patch("lecture_transcriber.main.transcribe_audio", return_value="text"),
            patch("lecture_transcriber.main.generate_notes_with_ollama", return_value="# Notes"),
            patch("lecture_transcriber.main.recording_extent") as measure,
        ):
            process_file(source, self.config, force=False, state=self.state)
        measure.assert_not_called()

    def test_superseding_pass_moves_note_when_class_resolves_later(self):
        self.run_partial(151.6, "first 2 minutes", "# Notes from 2 minutes")
        self.assertTrue((self.vault / "unknown_class" / "2026-08-04_09.22.47.md").exists())

        # The longer copy matches a calendar event that the first pass missed.
        self.config.calendar_rename.enabled = True
        source = self.source_dir / "2026-08-04 09.22.47.mp3"
        source.write_text("audio", encoding="utf-8")
        with (
            patch("lecture_transcriber.main.wait_for_file_stability", return_value=True),
            patch("lecture_transcriber.main.recording_extent", return_value=(2946.0, EXTENT_DURATION)),
            patch(
                "lecture_transcriber.main.find_class_info_for_timestamp",
                return_value=SimpleNamespace(class_name="Univ103", professor="Dr. Ames", building="Ames Hall"),
            ),
            patch("lecture_transcriber.main.transcribe_audio", return_value="the whole lecture"),
            patch("lecture_transcriber.main.generate_notes_with_ollama", return_value="# Full notes"),
        ):
            process_file(source, self.config, force=False, state=self.state)

        self.assertFalse((self.vault / "unknown_class" / "2026-08-04_09.22.47.md").exists())
        self.assertTrue((self.vault / "Univ103" / "univ103_08-04-2026_9.22.47AM.md").exists())


class BuildEntryTests(unittest.TestCase):
    def test_stores_paths_as_strings_and_stamps_time(self):
        entry = build_entry(
            key="20260804T092247",
            extent=2946.0,
            extent_kind=EXTENT_DURATION,
            transcript_path=Path(r"D:\transcripts\a.txt"),
            note_path=Path(r"D:\vault\a.md"),
            source_name="a.mp3",
            archive_path=Path(r"D:\archive\a.mp3"),
        )
        self.assertIsInstance(entry.transcript_path, str)
        self.assertEqual(entry.note, Path(r"D:\vault\a.md"))
        self.assertTrue(datetime.fromisoformat(entry.processed_at))

    def test_archive_path_defaults_to_empty_when_not_archived(self):
        entry = build_entry(
            key="k",
            extent=1.0,
            extent_kind=EXTENT_DURATION,
            transcript_path=Path("a.txt"),
            note_path=Path("a.md"),
            source_name="a.mp3",
        )
        self.assertEqual(entry.archive_path, "")


if __name__ == "__main__":
    unittest.main()
