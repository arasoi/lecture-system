import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def find_lecture_notes_template(vault_path: Path) -> Optional[str]:
    """Find and read the LectureNotesTemplate from the vault."""
    template_path = vault_path / "templates" / "LectureNotesTemplate.md"
    if template_path.exists():
        try:
            return template_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Could not read template: {exc}")
    return None


def generate_notes_with_ollama(transcript: str, model: str, prompt_template: str) -> str:
    """Generate lecture notes using Ollama."""
    prompt = prompt_template.format(transcript=transcript)
    
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Ollama failed: {result.stderr}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError("Ollama inference timed out after 5 minutes")
    except FileNotFoundError:
        raise RuntimeError("ollama command not found. Make sure ollama is installed and in PATH.")


def write_markdown(path: Path, content: str, template: Optional[str] = None) -> None:
    """Write markdown content to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    final_content = content
    if template:
        final_content = f"{template.strip()}\n\n{content}"
    path.write_text(final_content, encoding="utf-8")
