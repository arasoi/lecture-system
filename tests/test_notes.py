import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lecture_transcriber.notes import (
    OllamaError,
    build_markdown_with_template,
    find_lecture_notes_template,
    generate_notes_with_ollama,
)


class GenerateNotesTests(unittest.TestCase):
    def test_generate_notes_with_ollama_uses_utf8_for_non_ascii_transcript(self):
        transcript = "Café naïve — π"
        captured = {}

        def fake_run(*args, **kwargs):
            captured["text"] = kwargs.get("text")
            captured["encoding"] = kwargs.get("encoding")
            captured["errors"] = kwargs.get("errors")
            captured["input"] = kwargs.get("input")
            return SimpleNamespace(stdout="ok")

        with patch("lecture_transcriber.notes.subprocess.run", side_effect=fake_run):
            result = generate_notes_with_ollama(transcript, "model", "{transcript}")

        self.assertEqual(result, "ok")
        self.assertTrue(captured["text"])
        self.assertEqual(captured["encoding"], "utf-8")
        self.assertEqual(captured["errors"], "replace")
        self.assertEqual(captured["input"], transcript)

    def test_generate_notes_with_ollama_falls_back_to_cpu_on_gpu_error(self):
        transcript = "hello"
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise subprocess.CalledProcessError(
                    1,
                    args[0],
                    output="",
                    stderr="CUDA error: shared object initialization failed",
                )
            return SimpleNamespace(stdout="fallback ok")

        with patch("lecture_transcriber.notes.subprocess.run", side_effect=fake_run):
            result = generate_notes_with_ollama(transcript, "model", "{transcript}")

        self.assertEqual(result, "fallback ok")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("OLLAMA_LLM_LIBRARY", calls[0][1]["env"])
        self.assertEqual(calls[1][1]["env"]["OLLAMA_LLM_LIBRARY"], "cpu")

    def test_generate_notes_with_ollama_strips_thinking_tags(self):
        transcript = "hello"

        def fake_run(*args, **kwargs):
            return SimpleNamespace(stdout="<think>internal reasoning</think>\n# Lecture Notes\n- point")

        with patch("lecture_transcriber.notes.subprocess.run", side_effect=fake_run):
            result = generate_notes_with_ollama(transcript, "model", "{transcript}")

        self.assertEqual(result, "# Lecture Notes\n- point")

    def test_generate_notes_with_ollama_strips_thinking_fenced_block(self):
        transcript = "hello"

        def fake_run(*args, **kwargs):
            return SimpleNamespace(stdout="```thinking\nprivate chain of thought\n```\n\n## Summary\nDone")

        with patch("lecture_transcriber.notes.subprocess.run", side_effect=fake_run):
            result = generate_notes_with_ollama(transcript, "model", "{transcript}")

        self.assertEqual(result, "## Summary\nDone")

    def test_generate_notes_with_ollama_strips_plain_thinking_preamble(self):
        transcript = "hello"
        noisy_output = (
            "Thinking...\n"
            "internal planning line \x1b[K\n"
            "...done thinking.\n\n"
            "# Lecture Notes\n"
            "- point"
        )

        def fake_run(*args, **kwargs):
            return SimpleNamespace(stdout=noisy_output)

        with patch("lecture_transcriber.notes.subprocess.run", side_effect=fake_run):
            result = generate_notes_with_ollama(transcript, "model", "{transcript}")

        self.assertEqual(result, "# Lecture Notes\n- point")

    def test_build_markdown_with_template_prepends_template(self):
        result = build_markdown_with_template("# Notes", "## Template")
        self.assertEqual(result, "## Template\n\n# Notes")

    def test_build_markdown_with_template_populates_metadata_properties(self):
        template = "---\nClass Name:\nDate:\nTime:\n---"
        output_path = Path(r"C:\vault\Lectures\bio101\07-03-2026_1.00.00PM.md")
        result = build_markdown_with_template("# Notes", template, output_path=output_path)
        self.assertIn("Class Name: bio101", result)
        self.assertIn("Date: 07-03-2026", result)
        self.assertIn("Time: 1.00.00PM", result)

    def test_build_markdown_with_template_populates_metadata_with_class_prefix(self):
        template = "---\nClass Name:\nDate:\nTime:\n---"
        output_path = Path(r"C:\vault\Lectures\Cer101\cer101_07-04-2026_1.01.46PM.md")
        result = build_markdown_with_template("# Notes", template, output_path=output_path)
        self.assertIn("Class Name: Cer101", result)
        self.assertIn("Date: 07-04-2026", result)
        self.assertIn("Time: 1.01.46PM", result)

    def test_find_lecture_notes_template_prefers_templates_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ObsidianVault"
            lectures = root / "Lectures"
            templates = root / "templates"
            lectures.mkdir(parents=True, exist_ok=True)
            templates.mkdir(parents=True, exist_ok=True)
            template_path = templates / "LectureNotesTemplate.md"
            template_path.write_text("template", encoding="utf-8")

            found = find_lecture_notes_template(lectures)

            self.assertEqual(found, template_path)

    def test_generate_notes_with_ollama_raises_on_timeout(self):
        transcript = "hello"

        with patch(
            "lecture_transcriber.notes.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ollama", "run", "model"], timeout=1),
        ):
            with self.assertRaises(OllamaError):
                generate_notes_with_ollama(transcript, "model", "{transcript}")


if __name__ == "__main__":
    unittest.main()
