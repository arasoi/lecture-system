# Lecture Transcription Remote Installation Instructions

These instructions install and run the lecture transcription watcher on the remote workstation.

## Prerequisites

The remote machine must already have:

- Windows
- Python 3.11+ installed and available on `PATH`
- `ffmpeg` installed and available on `PATH`
- `ollama` installed and available on `PATH`
- Obsidian installed and configured with your vault
- OneDrive folder syncing the lecture recordings

## Package contents

The package includes:

- `lecture_transcriber/` — Python package with folder watcher, transcription, and note generation logic
- `config.example.yaml` — example configuration file
- `requirements.txt` — Python dependency list
- `scripts/bootstrap.ps1` — optional bootstrapper for Windows package install
- `scripts/install-watcher-task.ps1` — registers a scheduled task to run the watcher automatically
- `scripts/uninstall-watcher-task.ps1` — removes the scheduled task
- `README.md` — project overview and usage notes

## Installation steps

1. Transfer the package folder to the remote workstation.

2. Open PowerShell in the package folder.

3. Install Python dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Generate a configuration file:

```powershell
python -m lecture_transcriber --generate-config
```

When prompted, enter:

- OneDrive recordings source folder (the folder OBS writes recordings into)
- Obsidian notes folder (your vault or a lecture notes subfolder)
- Temporary working folder (e.g. `%USERPROFILE%\.lecture_transcriber\temp`)
- Transcript output folder (e.g. `%USERPROFILE%\.lecture_transcriber\transcripts`)
- Archive folder for processed recordings (optional)
- Error folder for failed recordings (optional)
- Whisper model name (for example `base`)
- Transcription device (`cpu` or `cuda`)
- Ollama model name

5. Confirm the generated `config.yaml` is correct.

## Verify the pipeline

Run once to validate the configuration and dependencies:

```powershell
python -m lecture_transcriber --config config.yaml --once
```

This will process any existing supported files in the source folder.

If using Graph device-code auth for calendar renaming, run one-time sign-in before scheduled/background runs:

```powershell
python -m lecture_transcriber --config config.yaml --graph-login
```

## Run continuously

To keep the watcher running and process new files automatically:

```powershell
python -m lecture_transcriber --config config.yaml
```

## Optional: install as a scheduled task

Register scheduled processing so it checks for new files on a recurring interval (including while locked):

```powershell
.\scripts\install-watcher-task.ps1 -TaskName "LectureTranscriberWatcher" -ConfigPath "C:\Program Files\Lecture System\config.yaml" -EveryMinutes 5
```

For calendar-based renaming, prefer `calendar_rename.provider: graph` with Graph credentials so event lookup works independently of classic/modern Outlook UI.

To remove the scheduled task later:

```powershell
.\scripts\uninstall-watcher-task.ps1 -TaskName "LectureTranscriberWatcher"
```

## Notes

- The watcher supports audio and video files with extensions: `.wav`, `.mp3`, `.m4a`, `.aac`, `.ogg`, `.flac`, `.opus`, `.mkv`, `.mp4`, `.mov`, `.avi`, `.webm`.
- Processed recordings can be moved to an archive folder automatically when `archive_dir` is configured.
- Failed recordings can be moved to an error folder automatically when `error_dir` is configured.
- Notes are written directly into the configured Obsidian notes folder in Markdown format.
- Generated lecture notes prepend `LectureNotesTemplate` from `<ObsidianVault>\templates\LectureNotesTemplate.md` and populate `Class Name`, `Date`, and `Time` when available.