# Debugging Outlook Calendar Matching

If recordings are still going to `unknown_class` instead of being matched to your calendar classes, use this guide.

## Step 1: Run the diagnostic script

```powershell
cd "C:\Program Files\Lecture System"
python diagnose_outlook.py
```

This will tell you:
- ✅ If Outlook calendar lookup is working
- ✅ If any events are found around the current time
- ❌ If there's an error accessing Outlook

## Step 2: Check your config.yaml

Make sure calendar_rename is enabled:

```yaml
calendar_rename:
  enabled: true
  provider: outlook
  lookback_minutes: 180
  lookahead_minutes: 180
```

## Step 3: Enable debug logging

Run with `--debug` flag to see detailed logs:

```powershell
python -m lecture_transcriber --config config.yaml --debug --once
```

Look for these log lines to understand what's happening:

- `Recording X has file creation time: YYYY-MM-DD HH:MM:SS` — Shows the file's creation timestamp
- `Looking up calendar event for...` — Shows the provider and search window
- `Resolved class 'ClassName' for recording X` — ✅ Success! Class was found
- `No calendar event found for X at time...` — ❌ No events found; check Outlook for events at that time
- `Calendar-based class lookup failed for X` — ❌ Error accessing Outlook; see error message for details

## Step 4: Verify Outlook has events

Check Outlook for calendar events:
1. Open Outlook
2. Look at your calendar for today
3. Make sure there are events with class names as the subject
4. Note the exact times of the events

## Step 5: Check timing

The raw recording file **creation time** (not modification time, but actual creation time from the file system) must fall within one of your Outlook events.

For example:
- If your Biology 101 class is 2:00 PM - 3:00 PM
- And you start recording at 2:05 PM
- The file creation time should show ~2:05 PM
- If it shows a different time, that's why it's not matching

You can check file creation time in PowerShell:

```powershell
$file = Get-Item "C:\Users\miste\OneDrive\Lectures\IncomingAudio\recording.m4a"
$file.CreationTime   # This is what the system uses for matching
$file.LastWriteTime  # This is different
```

## Step 6: If pywin32 is not installed

If you see errors about `pywin32` or cannot access Outlook:

```powershell
pip install pywin32
python -m pywin32_postinstall -install
```

This requires a script run to register COM interfaces. After that, restart PowerShell and try again.

## Step 7: Still not working?

Run the diagnostic script again after doing the above, and share the output. The logs will show exactly where the lookup is failing.
