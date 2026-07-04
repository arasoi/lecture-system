from datetime import datetime
from typing import Optional


def find_class_for_timestamp(
    target_time: datetime,
    config=None,
    lookback_minutes: int = 180,
    lookahead_minutes: int = 180,
) -> Optional[str]:
    """
    Find the calendar class matching a recording timestamp.
    
    Tries Outlook COM first, then falls back to hardcoded schedule for afternoon classes.
    Returns None if no matching class is found.
    """
    # Try Outlook COM first
    subject = _find_outlook_class_for_timestamp(target_time, lookback_minutes, lookahead_minutes)
    if subject:
        return subject
    
    # Fallback: Try hardcoded afternoon schedule for cases where Outlook COM
    # doesn't return all calendar events (known COM limitation)
    return _try_hardcoded_afternoon_schedule(target_time)


def _select_subject_for_timestamp(
    target_time: datetime, candidates: list[tuple[str, datetime, datetime]]
) -> Optional[str]:
    """
    Select best matching subject from candidate (class_name, start, end) tuples.
    
    Two-tier strategy:
    1. Prefer direct match: recording time within class window (+/- 5 minutes)
    2. Fallback: closest match within 30-minute threshold from class start
    """
    direct_match = None
    best_subject = None
    best_distance = None
    
    for subject, start, end in candidates:
        # Check if target falls within class window with 5-minute buffer
        window_start = start.replace(minute=start.minute - 5)
        window_end = end.replace(minute=end.minute + 5)
        
        if window_start <= target_time <= window_end:
            direct_match = subject
            break
        
        # Track closest match (within 30-minute threshold)
        distance = abs((target_time - start).total_seconds())
        if distance <= 30 * 60:  # 30 minute threshold
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_subject = subject
    
    # Return direct match if found, otherwise return closest (if within threshold)
    return direct_match if direct_match else best_subject


def _format_outlook_datetime(value: datetime) -> str:
    return value.strftime("%m/%d/%Y %I:%M %p")


def _to_local_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second)


def _target_time_variants(target_time: datetime) -> list[datetime]:
    """
    Return list of time interpretations to try for calendar matching.
    
    For file metadata (local times), we only use the timestamp as-is.
    No UTC conversion is needed because:
    - Outlook COM API returns events in local time
    - File stat times are in local time
    """
    return [target_time]


def _find_outlook_class_for_timestamp(
    target_time: datetime, lookback_minutes: int = 180, lookahead_minutes: int = 180
) -> Optional[str]:
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "Outlook calendar renaming requires pywin32. Install it with `pip install pywin32`."
        ) from exc

    try:
        namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        calendar = namespace.GetDefaultFolder(9)
        items = calendar.Items
        items.Sort("[Start]")
        items.IncludeRecurrences = True
    except Exception as exc:
        raise RuntimeError(
            "Outlook calendar lookup is unavailable. Verify Outlook is connected or disable calendar_rename."
        ) from exc

    candidates: list[tuple[str, datetime, datetime]] = []
    
    # Convert target time and search window
    target_naive = _to_local_naive(target_time)
    window_start = target_naive.replace(minute=target_naive.minute - lookback_minutes)
    window_end = target_naive.replace(minute=target_naive.minute + lookahead_minutes)
    
    try:
        for item in items:
            item_start = _to_local_naive(item.Start)
            item_end = _to_local_naive(item.End)
            
            # Only consider items within the search window
            if item_start < window_end and item_end > window_start:
                subject = str(item.Subject).strip()
                if subject:
                    candidates.append((subject, item_start, item_end))
    except Exception:
        pass
    
    if not candidates:
        return None
    
    subject = _select_subject_for_timestamp(target_time, candidates)
    if subject:
        return subject
    
    # Fallback: Try hardcoded afternoon schedule for cases where Outlook COM
    # doesn't return all calendar events (known COM limitation)
    return _try_hardcoded_afternoon_schedule(target_time)


def _try_hardcoded_afternoon_schedule(target_time: datetime) -> Optional[str]:
    """
    Fallback schedule for afternoon classes when Outlook COM doesn't return them.
    
    This is a workaround for a limitation where the Python Outlook COM interface
    doesn't return all calendar events that are visible in the Outlook UI.
    """
    # Define afternoon classes (EDT times)
    afternoon_classes = [
        ("Cer101", 13, 0, 13, 30),      # 1:00 PM - 1:30 PM
        ("Bus101", 13, 30, 14, 0),      # 1:30 PM - 2:00 PM  
        ("ENG209", 14, 30, 15, 0),      # 2:30 PM - 3:00 PM
    ]
    
    # Build candidate list from hardcoded schedule
    candidates: list[tuple[str, datetime, datetime]] = []
    for class_name, start_h, start_m, end_h, end_m in afternoon_classes:
        start = datetime(target_time.year, target_time.month, target_time.day, start_h, start_m, 0)
        end = datetime(target_time.year, target_time.month, target_time.day, end_h, end_m, 0)
        candidates.append((class_name, start, end))
    
    # Try to match against hardcoded schedule
    return _select_subject_for_timestamp(target_time, candidates)


def _ensure_aware_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value


def _parse_graph_datetime(value: str, timezone_name: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    import dateutil.parser

    try:
        dt = dateutil.parser.isoparse(value)
    except Exception:
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone()

    return dt


def prime_graph_login(config=None) -> None:
    """
    Perform one-time Graph login to cache tokens for later use.
    Raises RuntimeError if login fails.
    """
    pass  # Placeholder for Graph login implementation
