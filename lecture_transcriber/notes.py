import os
import re
import subprocess
from pathlib import Path
from typing import Optional


class OllamaError(RuntimeError):
    pass

DEFAULT_PROMPT_TEMPLATE = (
    "You are a lecture notes assistant. Summarize the following transcript into Obsidian-compatible "
    "Markdown notes with headings, bullet points, definitions, and examples.\n\n"
    "Transcript:\n{transcript}"
)

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
OLLAMA_TIMEOUT_SECONDS = 900


def _subprocess_window_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def build_prompt(prompt_template: str, transcript_text: str) -> str:
    template = (prompt_template or DEFAULT_PROMPT_TEMPLATE).strip()
    transcript = transcript_text.strip() or "No transcript available."

    if "{transcript}" not in template:
        template = f"{template}\n\nTranscript:\n{{transcript}}"

    prompt = template.replace("{transcript}", transcript)
    prompt = "\n".join(line.strip() for line in prompt.splitlines() if line.strip())
    return prompt.strip() or transcript


def strip_thinking_data(notes: str) -> str:
    cleaned = notes or ""
    cleaned = ANSI_ESCAPE_RE.sub("", cleaned)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(
        r"```(?:thinking|thought|thoughts|reasoning)\s*[\r\n].*?```",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"^\s*thinking\.\.\..*?(?:\.\.\.\s*done thinking\.?\s*)",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if re.match(r"^\s*thinking\b", cleaned, flags=re.IGNORECASE):
        first_heading = re.search(r"(?m)^#{1,6}\s+\S", cleaned)
        if first_heading:
            cleaned = cleaned[first_heading.start() :]
    cleaned = re.sub(r"(?mi)^\s*thinking\.\.\.\s*$", "", cleaned)
    cleaned = re.sub(r"(?mi)^\s*\.\.\.\s*done thinking\.?\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def generate_notes_with_ollama(transcript_text: str, model_name: str, prompt_template: str) -> str:
    prompt = build_prompt(prompt_template, transcript_text)
    env = os.environ.copy()
    env.pop("OLLAMA_LLM_LIBRARY", None)

    def run_ollama(current_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["ollama", "run", model_name],
            input=prompt,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=current_env,
            timeout=OLLAMA_TIMEOUT_SECONDS,
            **_subprocess_window_kwargs(),
        )

    try:
        result = run_ollama(env)
    except FileNotFoundError as exc:
        raise OllamaError("ollama is not installed or not available on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise OllamaError(
            f"Ollama timed out after {OLLAMA_TIMEOUT_SECONDS} seconds while generating notes."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        if "cuda" in stderr.lower() or "gpu" in stderr.lower() or "shared object initialization failed" in stderr.lower():
            cpu_env = os.environ.copy()
            cpu_env.pop("OLLAMA_LLM_LIBRARY", None)
            cpu_env["OLLAMA_LLM_LIBRARY"] = "cpu"
            try:
                result = run_ollama(cpu_env)
            except subprocess.TimeoutExpired as timeout_exc:
                raise OllamaError(
                    f"Ollama timed out after {OLLAMA_TIMEOUT_SECONDS} seconds while generating notes."
                ) from timeout_exc
            except subprocess.CalledProcessError as second_exc:
                second_stderr = (second_exc.stderr or "").strip()
                raise OllamaError(second_stderr or f"Ollama failed with exit code {second_exc.returncode}") from second_exc
            return strip_thinking_data(result.stdout)
        raise OllamaError(stderr or f"Ollama failed with exit code {exc.returncode}") from exc
    return strip_thinking_data(result.stdout)


def find_lecture_notes_template(notes_root: Path) -> Optional[Path]:
    template_names = ("LectureNotesTemplate.md", "LectureNotesTemplate")
    candidate_dirs = (
        notes_root / "templates",
        notes_root.parent / "templates",
        notes_root,
        notes_root.parent,
    )
    for directory in candidate_dirs:
        for name in template_names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _template_metadata_from_output_path(output_path: Path) -> dict[str, str]:
    class_name = output_path.parent.name
    stem = output_path.stem
    # Optional class prefix (e.g. "cer101_") before the date/time segment
    match = re.match(
        r"^(?:[^_]+_)?(?P<date>\d{2}-\d{2}-\d{4})_(?P<time>\d{1,2}\.\d{2}\.\d{2}(?:AM|PM))(?:_\d+)?$",
        stem,
        flags=re.IGNORECASE,
    )
    return {
        "Class Name": class_name,
        "Date": match.group("date") if match else "",
        "Time": match.group("time").upper() if match else "",
    }


def _apply_template_metadata(template_text: str, output_path: Path) -> str:
    metadata = _template_metadata_from_output_path(output_path)
    if not template_text.strip():
        return ""
    lines = []
    for line in template_text.splitlines():
        replaced = False
        for key, value in metadata.items():
            prefix = f"{key}:"
            if line.strip().startswith(prefix):
                lines.append(f"{prefix} {value}".rstrip())
                replaced = True
                break
        if not replaced:
            lines.append(line)
    return "\n".join(lines).strip()


def build_markdown_with_template(notes: str, template_text: str, output_path: Optional[Path] = None) -> str:
    notes_body = notes.strip()
    template_body = (
        _apply_template_metadata(template_text, output_path) if output_path is not None else template_text.strip()
    )
    if not template_body:
        return notes_body
    if not notes_body:
        return template_body
    return f"{template_body}\n\n{notes_body}"


def write_markdown(notes: str, output_path: Path, template_text: str = "") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_markdown = build_markdown_with_template(notes, template_text, output_path=output_path)
    output_path.write_text(final_markdown + "\n", encoding="utf-8")
