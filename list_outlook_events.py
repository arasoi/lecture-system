#!/usr/bin/env python3
"""
List all upcoming Outlook calendar events.
Shows you what events exist in your calendar so you can verify recording times.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import win32com.client
    from lecture_transcriber.config import load_config
except ImportError as e:
    print(f"Error importing: {e}")
    sys.exit(1)


def list_outlook_events():
    config_path = Path("config.yaml")
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    print(f"Loading config from: {config_path}")
    config = load_config(config_path)
    
    try:
        namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(9)
        items = calendar.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True
    except Exception as e:
        print(f"[ERROR] Cannot access Outlook calendar: {e}")
        return 1

    # Get events for today and tomorrow
    now = datetime.now()
    start_date = (now - timedelta(days=1)).date()
    end_date = (now + timedelta(days=1)).date()
    
    print(f"\nOutlook Calendar Events from {start_date} to {end_date}:")
    print("=" * 80)
    
    found_events = False
    for item in items:
        try:
            start = getattr(item, "Start", None)
            end = getattr(item, "End", None)
            subject = str(getattr(item, "Subject", "") or "").strip()
            
            if start is None or end is None or not subject:
                continue
            
            # Convert to local time
            if hasattr(start, 'astimezone'):
                start = start.astimezone()
            if hasattr(end, 'astimezone'):
                end = end.astimezone()
            
            start_date_obj = start.date() if hasattr(start, 'date') else start
            
            # Only show events in our date range
            if not (start_date <= start_date_obj <= end_date):
                continue
            
            found_events = True
            start_str = start.strftime("%Y-%m-%d %H:%M:%S") if hasattr(start, 'strftime') else str(start)
            end_str = end.strftime("%H:%M:%S") if hasattr(end, 'strftime') else str(end)
            
            print(f"[Event] {start_str} - {end_str}")
            print(f"        Subject: {subject}")
            print()
        except Exception as e:
            continue
    
    if not found_events:
        print("[INFO] No events found for today and tomorrow!")
        print("\n[ADVICE] Make sure you have calendar events scheduled in Outlook.")
        print("         The recording creation time must fall within an event's start/end times.")
    else:
        print("[OK] Found calendar events. Verify your recording times match these event times.")
    
    return 0 if found_events else 1


if __name__ == "__main__":
    sys.exit(list_outlook_events())
