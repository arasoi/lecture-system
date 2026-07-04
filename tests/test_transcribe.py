import importlib
import sys
import types
import unittest
from unittest.mock import patch

from lecture_transcriber.transcribe import is_audio_file, is_video_file


class LoadAudioBackendTest(unittest.TestCase):
    """Load the transcribe module to test file type detection."""

    def test_is_audio_file_with_common_formats(self):
        from pathlib import Path

        self.assertTrue(is_audio_file(Path("test.mp3")))
        self.assertTrue(is_audio_file(Path("test.wav")))
        self.assertTrue(is_audio_file(Path("test.m4a")))
        self.assertTrue(is_audio_file(Path("test.aac")))
        self.assertTrue(is_audio_file(Path("test.ogg")))
        self.assertTrue(is_audio_file(Path("test.flac")))
        self.assertTrue(is_audio_file(Path("test.opus")))

    def test_is_video_file_with_common_formats(self):
        from pathlib import Path

        self.assertTrue(is_video_file(Path("test.mkv")))
        self.assertTrue(is_video_file(Path("test.mp4")))
        self.assertTrue(is_video_file(Path("test.mov")))
        self.assertTrue(is_video_file(Path("test.avi")))
        self.assertTrue(is_video_file(Path("test.webm")))

    def test_mixed_case_extensions(self):
        from pathlib import Path

        self.assertTrue(is_audio_file(Path("test.MP3")))
        self.assertTrue(is_audio_file(Path("test.Wav")))
        self.assertTrue(is_video_file(Path("test.MP4")))
        self.assertTrue(is_video_file(Path("test.MKV")))

    def test_audio_video_not_cross_matched(self):
        from pathlib import Path

        self.assertFalse(is_audio_file(Path("test.mp4")))
        self.assertFalse(is_video_file(Path("test.mp3")))
        self.assertFalse(is_audio_file(Path("test.mkv")))
        self.assertFalse(is_video_file(Path("test.wav")))


if __name__ == "__main__":
    unittest.main()