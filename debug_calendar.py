#!/usr/bin/env python3
"""
Debug calendar lookup to see what's being matched.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import win32com.client
    from lecture_transcriber.calendar_lookup import _to_local_naive
    from lecture_transcriber.config import load_config
except ImportError as e:
    print(f"Error importing: {e}")
    sys.exit(1)


def debug_calendar_lookup(target_time):
    """Debug version of calendar lookup that shows all events and comparisons."""
    print(f"\n[DEBUG] Looking for events around: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(9)
        items = calendar.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True
    except Exception as e:
        print(f"[ERROR] Cannot access Outlook: {e}")
        return None

    # Build search window (180 min lookback/lookahead)
    window_start = target_time - timedelta(minutes=180)
    window_end = target_time + timedelta(minutes=180)
    
    print(f"[DEBUG] Search window: {window_start.strftime('%Y-%m-%d %H:%M:%S')} to {window_end.strftime('%Y-%m-%d %H:%M:%S')}")

    # Restrict to window
    from lecture_transcriber.calendar_lookup import _format_outlook_datetime
    restriction = (
        f"[Start] <= '{_format_outlook_datetime(window_end)}' AND "
        f"[End] >= '{_format_outlook_datetime(window_start)}'"
    )
    print(f"[DEBUG] Restriction filter: {restriction}\n")
    
    events = items.Restrict(restriction)
    print(f"[DEBUG] Found {events.Count} events in window\n")

    candidates = []
    for i, event in enumerate(events):
        subject = str(getattr(event, "Subject", "") or "").strip()
        start = getattr(event, "Start", None)
        end = getattr(event, "End", None)
        
        if start is None or end is None:
            continue

        start_time = _to_local_naive(start)
        end_time = _to_local_naive(end)
        
        print(f"[Event {i}] {subject}")
        print(f"           Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"           End:   {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Check if target falls within event
        if start_time <= target_time <= end_time:
            distance = abs((target_time - start_time).total_seconds())
            print(f"           STATUS: MATCH (distance from start: {distance} seconds)")
            candidates.append((subject, start_time, end_time, distance))
        else:
            gap_before = (target_time - end_time).total_seconds()
            gap_after = (start_time - target_time).total_seconds()
            if gap_before > 0:
                print(f"           STATUS: BEFORE (gap: {gap_before} seconds after event ends)")
            elif gap_after > 0:
                print(f"           STATUS: AFTER (gap: {gap_after} seconds before event starts)")
            else:
                print(f"           STATUS: NOT IN RANGE")
        print()
    
    if candidates:
        # Pick the one with smallest distance
        best = min(candidates, key=lambda x: x[3])
        print(f"[RESULT] Selected: {best[0]}")
        return best[0]
    else:
        print(f"[RESULT] No matching events found")
        return None


def main():
    config_path = Path("config.yaml")
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    config = load_config(config_path)
    
    # Test time: 9:15 AM (during Cer101 9:00-9:30)
    test_time = datetime(2026, 7, 4, 9, 15, 0)
    
    result = debug_calendar_lookup(test_time)
    
    if result:
        print(f"\n[SUCCESS] Matched to: {result}")
        return 0
    else:
        print(f"\n[FAILURE] No match")
        return 1


if __name__ == "__main__":
    sys.exit(main())
