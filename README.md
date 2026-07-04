# Lecture Transcription Pipeline

This project provides a local workflow for recording lectures on a laptop, syncing them through OneDrive, and converting recorded audio/video into Obsidian lecture notes on a remote workstation.

## Architecture

1. Record lecture audio/video to a OneDrive-synced folder on the laptop.
2. A remote workstation watches the synced folder for new files.
3. The workstation extracts audio, transcribes it locally, and generates Obsidian-ready Markdown lecture notes using a local Ollama model.
4. Notes are written into an Obsidian vault.

## What this repository contains

- `lecture_transcriber/` — Python package implementing the folder watcher, transcription pipeline, and Ollama note generation.
- `config.example.yaml` — example configuration.
- `requirements.txt` — Python dependencies.
- `scripts/bootstrap.ps1` — Windows bootstrap script for installing required software.

## Prerequisites

On the remote workstation:

- Windows with OneDrive sync enabled.
- `ffmpeg` installed and available on `PATH`.
- `Python 3.11+` installed.
- `ollama` installed and configured with a local model.
- Python packages installed from `requirements.txt`.

## Installation

1. Install Python, ffmpeg, and Ollama.
2. Install dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Copy `config.example.yaml` to `config.yaml` and update the paths.

## Configuration

Edit `config.yaml` and set:

- `source_dir` — OneDrive folder to watch for new recordings.
- `obsidian_vault_dir` — path to the Obsidian vault or notes folder.
- `temp_dir` — temporary working directory used during processing.
- `transcript_dir` — folder for raw transcripts.
- `archive_dir` — optional folder to move processed recordings after success.
- `error_dir` — optional folder to move failed recordings for review.
- `ollama.model` — local Ollama model name.
- `calendar_rename.provider` — `graph`, `outlook`, or `auto`.
- `calendar_rename.graph_*` — Graph credentials/mailbox settings when using `graph`.
- `calendar_rename.graph_auth_mode` — `device_code` (personal-friendly) or `client_credentials` (app secret).

## Generating a starter config

Use the built-in generator to scaffold `config.yaml`:

```powershell
python -m lecture_transcriber --generate-config
```

## Running

Run the watcher on the remote workstation:

```powershell
python -m lecture_transcriber --config config.yaml
```

If using `graph_auth_mode: device_code`, run one-time login first:

```powershell
python -m lecture_transcriber --config config.yaml --graph-login
```

The service will watch for new MKV, MP4, WAV and supported audio files, extract audio when needed, transcribe it, and generate Markdown notes.

If a recording filename matches `Class_Name_MM-DD-YYYY_h.mm.ssAM/PM` (for example, `bio101_07-03-2026_1.00.00PM.m4a`), notes are written to:

- `<obsidian_vault_dir>\Class_Name\Class_Name_MM-DD-YYYY_h.mm.ssAM/PM.md`

The class folder is created automatically if it does not exist.
If a recording does not match the class/date/time pattern, notes are saved under `<obsidian_vault_dir>\unknown_class\`.

## Notes generation

This code uses `ollama predict` to run the configured local model. Make sure the model is installed locally in Ollama and that `ollama` is in `PATH`.
Each generated lecture note prepends `LectureNotesTemplate` from the Obsidian vault templates folder (`<vault>\templates\LectureNotesTemplate.md`) and fills `Class Name`, `Date`, and `Time` from the output path when available.

## Calendar-based renaming (Microsoft Graph)

Enable `calendar_rename` in `config.yaml` to auto-rename incoming recordings from calendar events:

```yaml
calendar_rename:
  enabled: true
  provider: "graph"
  graph_auth_mode: "device_code"
  lookback_minutes: 180
  lookahead_minutes: 180
  graph_tenant_id: "consumers"
  graph_client_id: "<your-public-client-id>"
  graph_mailbox_user: ""
  graph_token_cache_path: "C:/Users/you/.lecture_transcriber/graph_token_cache.json"
```

When enabled, files are renamed to `Class_Name_MM-DD-YYYY_h.mm.ssAM/PM` using the closest calendar event.

When enabled, files are matched to Outlook/Graph classes using the raw recording file creation timestamp. The resolved class + timestamp are then reused for raw filename renaming, transcript naming, and Obsidian note folder/file naming so sorting stays consistent.

Set `provider: "auto"` to use Graph when Graph settings for the selected `graph_auth_mode` are configured, otherwise fall back to local Outlook COM lookup.

## Running as a Windows scheduled task

A helper script is included to register scheduled processing on the remote workstation. It runs on a recurring interval (each run uses `--once`) and continues while the workstation is locked.

Graph-based renaming works regardless of classic or modern Outlook client because it reads mailbox data from Microsoft 365/Exchange Online via Graph.

```powershell
.\scripts\install-watcher-task.ps1 -TaskName "LectureTranscriberWatcher" -ConfigPath "C:\Program Files\Lecture System\config.yaml" -EveryMinutes 5
```

The installer runs in silent mode by default (no command window pop-up). Pass `-Silent $false` if you want a visible console process.

If you need to remove the task later:

```powershell
.\scripts\uninstall-watcher-task.ps1 -TaskName "LectureTranscriberWatcher"
```