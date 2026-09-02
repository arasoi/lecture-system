import os
import queue
import tempfile
import time
import unittest
from pathlib import Path

from lecture_transcriber.watch_folder import (
    FileProcessorQueue,
    recording_is_quiet,
    seconds_since_last_write,
)


def write_with_age(path: Path, age_seconds: float) -> Path:
    """Create a file whose last-write time is `age_seconds` in the past."""
    path.write_text("audio", encoding="utf-8")
    when = time.time() - age_seconds
    os.utime(path, (when, when))
    return path


class QuietPeriodTests(unittest.TestCase):
    """A recording is only finished once nothing has written to it for a while."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def test_recording_written_recently_is_not_quiet(self):
        # A file sitting between OneDrive sync bursts looks stable but is not finished.
        path = write_with_age(self.root / "partial.mp3", age_seconds=600)
        self.assertFalse(recording_is_quiet(path, quiet_seconds=1200))

    def test_recording_untouched_past_the_quiet_period_is_quiet(self):
        path = write_with_age(self.root / "finished.mp3", age_seconds=1500)
        self.assertTrue(recording_is_quiet(path, quiet_seconds=1200))

    def test_zero_quiet_period_disables_the_check(self):
        path = write_with_age(self.root / "fresh.mp3", age_seconds=0)
        self.assertTrue(recording_is_quiet(path, quiet_seconds=0))

    def test_future_timestamp_is_treated_as_just_written(self):
        # Clock skew between the recording laptop and this workstation must defer the
        # recording, not let it through early.
        path = write_with_age(self.root / "skewed.mp3", age_seconds=-600)
        self.assertEqual(seconds_since_last_write(path), 0.0)
        self.assertFalse(recording_is_quiet(path, quiet_seconds=1200))

    def test_reports_age_since_last_write(self):
        path = write_with_age(self.root / "aged.mp3", age_seconds=300)
        self.assertAlmostEqual(seconds_since_last_write(path), 300, delta=5)


class WatchFolderTests(unittest.TestCase):
    def test_enqueue_retries_when_queue_is_full(self):
        processor = FileProcessorQueue(lambda _: None)
        calls = {"count": 0}

        def fake_put(item, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                raise queue.Full()
            return None

        processor.queue.put = fake_put
        processor.enqueue(Path("sample.wav"))
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
