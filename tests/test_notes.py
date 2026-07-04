import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lecture_transcriber.notes import (
    find_lecture_notes_template,
    generate_notes_with_ollama,
    write_markdown,
)


class FindLectureNotesTemplateTest(unittest.TestCase):
    def test_reads_template_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            template_dir = vault / "templates"
            template_dir.mkdir()
            template_file = template_dir / "LectureNotesTemplate.md"
            template_file.write_text("# Template\nContent", encoding="utf-8")

            result = find_lecture_notes_template(vault)
            self.assertEqual(result, "# Template\nContent")

    def test_returns_none_when_template_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir)
            result = find_lecture_notes_template(vault)
            self.assertIsNone(result)


class GenerateNotesWithOllamaTest(unittest.TestCase):
    def test_calls_ollama_with_formatted_prompt(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = SimpleNamespace(returncode=0, stdout="Generated notes")

            result = generate_notes_with_ollama("Test transcript", "llama2", "Summarize: {transcript}")

            self.assertEqual(result, "Generated notes")
            mock_run.assert_called_once()

    def test_raises_on_ollama_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = SimpleNamespace(returncode=1, stderr="Error")

            with self.assertRaises(RuntimeError):
                generate_notes_with_ollama("Test", "llama2", "Summarize: {transcript}")

    def test_raises_on_timeout(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ollama", 300)

            with self.assertRaises(RuntimeError):
                generate_notes_with_ollama("Test", "llama2", "Summarize: {transcript}")


class WriteMarkdownTest(unittest.TestCase):
    def test_writes_content_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.md"
            write_markdown(path, "Test content")

            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "Test content")

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "dirs" / "test.md"
            write_markdown(path, "Test content")

            self.assertTrue(path.exists())
            self.assertTrue(path.parent.exists())

    def test_prepends_template_when_provided(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.md"
            write_markdown(path, "Body", template="# Template\n")

            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# Template"))
            self.assertIn("Body", content)


if __name__ == "__main__":
    unittest.main()