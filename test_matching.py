#!/usr/bin/env python3
"""
Test class matching with a specific file and timestamp.
"""
import sys
from datetime import datetime
from pathlib import Path

try:
    from lecture_transcriber.main import resolve_recording_context, rename_file_for_calendar
    from lecture_transcriber.config import load_config
except ImportError as e:
    print(f"Error importing: {e}")
    sys.exit(1)


def main():
    config_path = Path("config.yaml")
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        return 1

    config = load_config(config_path)
    
    # Test file created during Cer101 (9:00-9:30 AM)
    test_file = Path("test_recordings/test_recording.m4a")
    
    if not test_file.exists():
        print(f"[ERROR] Test file not found: {test_file}")
        return 1
    
    print(f"Test File: {test_file}")
    print(f"File creation time: {datetime.fromtimestamp(test_file.stat().st_ctime).strftime('%Y-%m-%d %H:%M:%S')}")
    
    print("\n[TEST] Resolving recording context...")
    context = resolve_recording_context(test_file, config)
    
    print(f"[Result] Created time: {context.created_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[Result] Class name: {context.class_name}")
    
    if context.class_name:
        print(f"\n[OK] Class matched! Now testing rename...")
        renamed = rename_file_for_calendar(test_file, context)
        print(f"[OK] Would be renamed to: {renamed.name}")
        print(f"\nFull path: {renamed}")
        return 0
    else:
        print(f"\n[FAIL] No class matched")
        return 1


if __name__ == "__main__":
    sys.exit(main())
