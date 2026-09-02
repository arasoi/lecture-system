#!/usr/bin/env python3
"""
Simple debug - just iterate all calendar events and show them.
"""
import sys
from datetime import datetime
from pathlib import Path

try:
    import win32com.client
    from lecture_transcriber.calendar_lookup import _to_local_naive
except ImportError as e:
    print(f"Error importing: {e}")
    sys.exit(1)


def main():
    try:
        namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(9)
        items = calendar.Items
        items.Sort("[Start]")
    except Exception as e:
        print(f"[ERROR] Cannot access Outlook: {e}")
        return 1

    print("[INFO] Iterating through ALL calendar items...\n")
    
    count = 0
    for item in items:
        try:
            subject = str(getattr(item, "Subject", "") or "").strip()
            start = getattr(item, "Start", None)
            end = getattr(item, "End", None)
            
            if not subject or start is None or end is None:
                continue
            
            start_time = _to_local_naive(start)
            end_time = _to_local_naive(end)
            
            # Only show events from July 4, 2026
            if start_time.date().year != 2026 or start_time.date().month != 7 or start_time.date().day != 4:
                continue
            
            count += 1
            print(f"[Event {count}] {subject}")
            print(f"            Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"            End:   {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Test if 9:15 AM falls within this event
            test_time = datetime(2026, 7, 4, 9, 15, 0)
            if start_time <= test_time <= end_time:
                print(f"            >> 9:15 AM FALLS WITHIN THIS EVENT")
            print()
        except Exception as e:
            continue
    
    if count > 0:
        print(f"[OK] Found {count} events on July 4, 2026")
        return 0
    else:
        print(f"[ERROR] No events found!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
