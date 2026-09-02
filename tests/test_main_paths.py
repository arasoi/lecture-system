import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lecture_transcriber.calendar_lookup import CalendarEventInfo
from lecture_transcriber.main import (
    RecordingContext,
    ensure_unique_output_paths,
    get_output_paths,
    process_file,
    reclassify_unknown_notes,
    recording_timestamp_from_filename,
    rename_file_for_calendar,
    resolve_recording_context,
)


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            transcript_dir=Path(r"D:\LectureFolders\Transcripts"),
            obsidian_vault_dir=Path(r"D:\ObsidianVault\Lectures\Lecture Notes"),
        )

    def test_uses_class_folder_and_date_for_calendar_style_name(self):
        source = Path(r"C:\Users\miste\OneDrive\Lectures\IncomingAudio\Biology_101_07-02-2026_2.30.00PM.m4a")
        transcript_path, note_path = get_output_paths(source, self.config)

        self.assertEqual(transcript_path, self.config.transcript_dir / "biology_101_07-02-2026_2.30.00PM.txt")
        self.assertEqual(
            note_path,
            self.config.obsidian_vault_dir / "Biology_101" / "biology_101_07-02-2026_2.30.00PM.md",
        )

    def test_routes_non_calendar_style_name_to_unknown_class_folder(self):
        source = Path(r"C:\Users\miste\OneDrive\Lectures\IncomingAudio\random_capture.m4a")
        _, note_path = get_output_paths(source, self.config)
        self.assertEqual(note_path, self.config.obsidian_vault_dir / "unknown_class" / "random_capture.md")

    def test_calendar_style_name_with_suffix_still_routes_to_class_folder(self):
        source = Path(r"C:\Users\miste\OneDrive\Lectures\IncomingAudio\Biology_101_1_07-02-2026_2.30.00PM.m4a")
        _, note_path = get_output_paths(source, self.config)
        self.assertEqual(
            note_path,
            self.config.obsidian_vault_dir / "Biology_101_1" / "biology_101_1_07-02-2026_2.30.00PM.md",
        )

    def test_uses_recording_context_for_output_sorting_and_class_prefix(self):
        source = Path(r"C:\Users\miste\OneDrive\Lectures\IncomingAudio\2026-07-04_13-01-19.m4a")
        context = RecordingContext(created_time=datetime(2026, 7, 4, 13, 1, 19), class_name="Cer101")
        transcript_path, note_path = get_output_paths(source, self.config, context=context)

        self.assertEqual(transcript_path, self.config.transcript_dir / "cer101_07-04-2026_1.01.19PM.txt")
        self.assertEqual(note_path, self.config.obsidian_vault_dir / "Cer101" / "cer101_07-04-2026_1.01.19PM.md")

    def test_renames_recording_using_outlook_class_and_date(self):
        with self.subTest("calendar rename enabled"):
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir) / "recording.m4a"
                temp_path.write_text("audio", encoding="utf-8")
                renamed = rename_file_for_calendar(
                    temp_path,
                    RecordingContext(created_time=datetime(2026, 7, 4, 13, 1, 19), class_name="Physics 201"),
                )
                self.assertEqual(renamed.name, "physics_201_07-04-2026_1.01.19PM.m4a")

    def test_keeps_original_filename_when_calendar_event_not_found(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "recording.m4a"
            temp_path.write_text("audio", encoding="utf-8")
            unchanged = rename_file_for_calendar(
                temp_path,
                RecordingContext(created_time=datetime(2026, 7, 4, 13, 1, 19), class_name=None),
            )
            self.assertEqual(unchanged, temp_path)

    def test_keeps_original_filename_when_outlook_lookup_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "recording.m4a"
            temp_path.write_text("audio", encoding="utf-8")
            config = SimpleNamespace(
                calendar_rename=SimpleNamespace(enabled=True, lookback_minutes=180, lookahead_minutes=180)
            )
            with (
                patch(
                    "lecture_transcriber.main.recording_timestamp_from_file_metadata",
                    return_value=datetime(2026, 7, 4, 13, 1, 19),
                ),
                patch(
                    "lecture_transcriber.main.find_class_info_for_timestamp",
                    side_effect=RuntimeError("Outlook calendar lookup is unavailable."),
                ),
            ):
                context = resolve_recording_context(temp_path, config)
                unchanged = rename_file_for_calendar(temp_path, context)
            self.assertIsNone(context.class_name)
            self.assertEqual(unchanged, temp_path)

    def test_uses_unique_output_paths_when_note_or_transcript_already_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript_path = root / "raw" / "transcripts" / "capture.txt"
            note_path = root / "notes" / "capture.md"

            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text("existing note", encoding="utf-8")

            unique_transcript, unique_note = ensure_unique_output_paths(transcript_path, note_path)

            self.assertEqual(unique_transcript.name, "capture_1.txt")
            self.assertEqual(unique_note.name, "capture_1.md")

    def test_routes_file_to_error_dir_when_calendar_rename_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "incoming.m4a"
            source.write_text("audio", encoding="utf-8")
            error_dir = root / "errors"
            config = SimpleNamespace(
                temp_dir=root / "temp",
                transcription=SimpleNamespace(model="base", device="cpu"),
                ollama=SimpleNamespace(model="llama2", prompt_template="{transcript}"),
                archive_dir=None,
                error_dir=error_dir,
                obsidian_vault_dir=root / "vault",
                transcript_dir=root / "transcripts",
                calendar_rename=SimpleNamespace(enabled=True, lookback_minutes=180, lookahead_minutes=180),
                quiet_period_minutes=0,
            )

            with (
                patch("lecture_transcriber.main.wait_for_file_stability", return_value=True),
                patch("lecture_transcriber.main.rename_file_for_calendar", side_effect=ValueError("boom")),
            ):
                process_file(source, config, force=False)

            self.assertFalse(source.exists())
            self.assertTrue((error_dir / "incoming.m4a").exists())

    def test_parses_recording_timestamp_from_filename_patterns(self):
        self.assertEqual(
            recording_timestamp_from_filename("2026-07-04 15-21-23"),
            datetime(2026, 7, 4, 15, 21, 23),
        )
        self.assertEqual(
            recording_timestamp_from_filename("2026-07-04_15.21.23"),
            datetime(2026, 7, 4, 15, 21, 23),
        )
        self.assertEqual(
            recording_timestamp_from_filename("recording_20260704_144447"),
            datetime(2026, 7, 4, 14, 44, 47),
        )
        self.assertEqual(
            recording_timestamp_from_filename("capture_07-04-2026_15-21-23"),
            datetime(2026, 7, 4, 15, 21, 23),
        )
        self.assertEqual(
            recording_timestamp_from_filename("capture_07-04-2026_1.21.23PM"),
            datetime(2026, 7, 4, 13, 21, 23),
        )

    def test_resolve_context_uses_file_created_timestamp_for_calendar_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "recording.m4a"
            temp_path.write_text("audio", encoding="utf-8")

            seen = {}

            def fake_lookup(target_time, config, lookback_minutes, lookahead_minutes):
                seen["target_time"] = target_time
                return CalendarEventInfo(class_name="Physics 201", professor="Dr. Jones", building="Ames Hall")

            with (
                patch("lecture_transcriber.main.find_class_info_for_timestamp", side_effect=fake_lookup),
                patch(
                    "lecture_transcriber.main.recording_timestamp_from_file_metadata",
                    return_value=datetime(2026, 7, 4, 15, 21, 23),
                ),
            ):
                context = resolve_recording_context(
                    temp_path,
                    SimpleNamespace(
                        calendar_rename=SimpleNamespace(
                            enabled=True, lookback_minutes=180, lookahead_minutes=180
                        )
                    ),
                )

            self.assertEqual(seen["target_time"].strftime("%Y-%m-%d %H:%M:%S"), "2026-07-04 15:21:23")
            self.assertEqual(context.class_name, "Physics 201")
            self.assertEqual(context.professor, "Dr. Jones")
            self.assertEqual(context.building, "Ames Hall")

    def test_resolve_context_prefers_filename_timestamp_for_calendar_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "2026-07-04_13-01-19.m4a"
            temp_path.write_text("audio", encoding="utf-8")

            seen = {}

            def fake_lookup(target_time, config, lookback_minutes, lookahead_minutes):
                seen["target_time"] = target_time
                return CalendarEventInfo(class_name="Cer101", professor="Dr. Smith", building="Science Center")

            with (
                patch("lecture_transcriber.main.find_class_info_for_timestamp", side_effect=fake_lookup),
                patch(
                    "lecture_transcriber.main.recording_timestamp_from_file_metadata",
                    return_value=datetime(2026, 7, 4, 9, 0, 0),
                ),
            ):
                context = resolve_recording_context(
                    temp_path,
                    SimpleNamespace(
                        calendar_rename=SimpleNamespace(
                            enabled=True, lookback_minutes=180, lookahead_minutes=180
                        )
                    ),
                )

            # Filename timestamp (13:01:19) should be preferred over file metadata (09:00:00)
            self.assertEqual(seen["target_time"], datetime(2026, 7, 4, 13, 1, 19))
            self.assertEqual(context.class_name, "Cer101")
            self.assertEqual(context.created_time, datetime(2026, 7, 4, 13, 1, 19))
            self.assertEqual(context.professor, "Dr. Smith")
            self.assertEqual(context.building, "Science Center")

    def test_reclassifies_unknown_notes_into_class_folders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = root / "Lectures"
            unknown = vault / "unknown_class"
            unknown.mkdir(parents=True, exist_ok=True)
            note = unknown / "2026-07-04_13-01-19.md"
            note.write_text(
                "---\nClass Name: unknown_class\nProfessor:\nBuilding:\nDate:\nTime:\n---\n\ncontent\n",
                encoding="utf-8",
            )

            config = SimpleNamespace(
                obsidian_vault_dir=vault,
                calendar_rename=SimpleNamespace(lookback_minutes=180, lookahead_minutes=180),
            )

            with patch(
                "lecture_transcriber.main.find_class_info_for_timestamp",
                return_value=CalendarEventInfo(class_name="Cer101", professor="Dr. Smith", building="Ames Hall"),
            ):
                reclassify_unknown_notes(config)

            self.assertFalse(note.exists())
            # Canonical name built from parsed timestamp: MM-DD-YYYY_H.MM.SSam/pm
            destination = vault / "cer101" / "cer101_07-04-2026_1.01.19PM.md"
            self.assertTrue(destination.exists())
            self.assertIn("Professor: Dr. Smith", destination.read_text(encoding="utf-8"))
            self.assertIn("Building: Ames Hall", destination.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
