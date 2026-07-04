import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from lecture_transcriber.main import (
    parse_class_and_date,
    recording_timestamp_from_filename,
)


class RecordingTimestampFromFilenameTest(unittest.TestCase):
    def test_matches_iso_8601_date_time_with_dashes_in_time(self):
        stem = "2026-07-04 13-01-19"
        result = recording_timestamp_from_filename(stem)
        self.assertEqual(result, datetime(2026, 7, 4, 13, 1, 19))

    def test_matches_iso_8601_date_with_dots_in_time(self):
        stem = "2026-07-04 13.03.08"
        result = recording_timestamp_from_filename(stem)
        self.assertEqual(result, datetime(2026, 7, 4, 13, 3, 8))

    def test_matches_compact_datetime_format(self):
        stem = "20260704 130119"
        result = recording_timestamp_from_filename(stem)
        self.assertEqual(result, datetime(2026, 7, 4, 13, 1, 19))

    def test_matches_us_date_format_with_dashes_in_time(self):
        stem = "07-04-2026 13-01-19"
        result = recording_timestamp_from_filename(stem)
        self.assertEqual(result, datetime(2026, 7, 4, 13, 1, 19))

    def test_no_match_returns_none(self):
        stem = "random_text"
        result = recording_timestamp_from_filename(stem)
        self.assertIsNone(result)

    def test_does_not_match_embedded_timestamp_without_boundaries(self):
        """Numbers without clear boundaries should not match."""
        stem = "abc2026070413011920261231235959def"
        result = recording_timestamp_from_filename(stem)
        self.assertIsNone(result)


class ParseClassAndDateTest(unittest.TestCase):
    def test_parses_modern_format(self):
        stem = "bio101_07-04-2026_1.01.19PM"
        result = parse_class_and_date(stem)
        self.assertEqual(result, ("bio101", "07-04-2026", "1.01.19PM"))

    def test_parses_class_with_spaces(self):
        stem = "Bio 101_07-04-2026_1.01.19PM"
        result = parse_class_and_date(stem)
        # Sanitize step converts "Bio 101" -> "Bio 101"
        self.assertEqual(result, ("Bio 101", "07-04-2026", "1.01.19PM"))

    def test_parses_class_with_numbers_and_underscores(self):
        stem = "CHEM_2B_07-04-2026_1.01.19PM"
        result = parse_class_and_date(stem)
        self.assertEqual(result, ("CHEM_2B", "07-04-2026", "1.01.19PM"))

    def test_case_insensitive_time_suffix(self):
        """Should work with both AM and PM in any case."""
        for time_suffix in ["1.01.19PM", "1.01.19pm", "1.01.19Pm", "1.01.19AM"]:
            stem = f"bio101_07-04-2026_{time_suffix}"
            result = parse_class_and_date(stem)
            # Uppercase conversion: should uppercase PM/AM in output
            self.assertIsNotNone(result)
            self.assertEqual(result[0], "bio101")
            self.assertEqual(result[1], "07-04-2026")

    def test_no_match_returns_none(self):
        stem = "random_text"
        result = parse_class_and_date(stem)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()