from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import CalendarRenameConfig

GRAPH_SCOPES = ["Calendars.Read"]
PLACEHOLDER_CLIENT_IDS = {"your_public_client_id_here", "your-client-id", "client_id_here"}


@dataclass
class CalendarEventInfo:
    """Information extracted from a matched calendar event."""
    class_name: str
    professor: Optional[str] = None
    building: Optional[str] = None


def _parse_labeled_value_from_body(body: str, labels: tuple[str, ...]) -> Optional[str]:
    for line in (body or "").splitlines():
        for label in labels:
            m = re.match(rf"^\s*{re.escape(label)}\.?\s*[:\-]\s*(.+)$", line, flags=re.IGNORECASE)
            if m:
                value = m.group(1).strip()
                return value if value else None
    return None


def _parse_professor_from_body(body: str) -> Optional[str]:
    """
    Extract a professor name from calendar event body text.

    Looks for a line matching one of:
        Professor: Dr. Smith
        Prof: Smith
        Professor - Dr. Smith
    Returns the name stripped, or None if not found.
    """
    return _parse_labeled_value_from_body(body, ("Professor", "Prof"))


def _parse_building_from_body(body: str) -> Optional[str]:
    """Extract a building name from calendar event body text."""
    return _parse_labeled_value_from_body(body, ("Building",))


# Internal event tuple: (subject, start_time, end_time, professor_or_None, building_or_None)
_EventTuple = tuple[str, datetime, datetime, Optional[str], Optional[str]]


def _select_event_for_timestamp(target_time: datetime, events: list[_EventTuple]) -> Optional[CalendarEventInfo]:
    """
    Find the best matching event for a target time.
    
    Strategy:
    1. Prefer events where target_time falls within [start - 5min, end + 5min]
    2. If no direct match, consider closest event if it's within 30 minutes
    3. Return None if no reasonable match found
    
    This allows for recordings that start slightly before/after class but are
    clearly intended for that class (e.g., 1:01 PM recording for 1:00 PM class).
    """
    best_event: Optional[_EventTuple] = None
    best_distance = None
    direct_match_event: Optional[_EventTuple] = None
    direct_match_distance = None
    
    max_distance_threshold = timedelta(minutes=30)
    event_buffer = timedelta(minutes=5)
    
    for entry in events:
        subject, start_time, end_time, professor, building = entry
        if not subject:
            continue
        
        # Preference 1: Recording within event window (or within 5 minutes before/after)
        if (start_time - event_buffer) <= target_time <= (end_time + event_buffer):
            distance_seconds = abs((target_time - start_time).total_seconds())
            if direct_match_distance is None or distance_seconds < direct_match_distance:
                direct_match_distance = distance_seconds
                direct_match_event = entry
        
        # Preference 2: Closest event (only if reasonably close)
        distance = abs(target_time - start_time)
        if distance <= max_distance_threshold:
            distance_seconds = distance.total_seconds()
            if best_distance is None or distance_seconds < best_distance:
                best_distance = distance_seconds
                best_event = entry
    
    # Return direct match if found, otherwise return closest (if within threshold)
    chosen = direct_match_event if direct_match_event else best_event
    if chosen is None:
        return None
    subject, _start, _end, professor, building = chosen
    return CalendarEventInfo(class_name=subject, professor=professor, building=building)


def _select_subject_for_timestamp(target_time: datetime, events: list[_EventTuple]) -> Optional[str]:
    """Thin wrapper — returns only the class name string for backward compatibility."""
    info = _select_event_for_timestamp(target_time, events)
    return info.class_name if info else None


def _format_outlook_datetime(value: datetime) -> str:
    return value.strftime("%m/%d/%Y %I:%M %p")


def _to_local_naive(value: datetime) -> datetime:
    """
    Convert a datetime to naive local time.
    
    IMPORTANT: Outlook COM returns times with a UTC offset marker, but the 
    underlying times are actually in local time (EDT/EST). If we call 
    astimezone() on these, it will incorrectly interpret the "UTC" marker 
    and convert 1:00 PM (marked as UTC) to 9:00 AM EDT.
    
    Solution: Simply strip the timezone info without converting, since the 
    time values are already in local time.
    """
    if value.tzinfo is not None:
        # Just remove the timezone info - don't convert
        return value.replace(tzinfo=None)
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


def _find_outlook_event_info_for_timestamp(
    target_time: datetime, lookback_minutes: int = 180, lookahead_minutes: int = 180
) -> Optional[CalendarEventInfo]:
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

    target_variants = _target_time_variants(target_time)
    window_start = min(target_variants) - timedelta(minutes=lookback_minutes)
    window_end = max(target_variants) + timedelta(minutes=lookahead_minutes)

    candidates: list[_EventTuple] = []

    # Iterate through all items and filter manually (Restrict() doesn't iterate properly)
    for event in items:
        subject = str(getattr(event, "Subject", "") or "").strip()
        if not subject:
            continue

        start = getattr(event, "Start", None)
        end = getattr(event, "End", None)
        if start is None or end is None:
            continue

        start_time = _to_local_naive(start)
        end_time = _to_local_naive(end)
        
        # Only include events in the search window
        if end_time < window_start or start_time > window_end:
            continue

        body = str(getattr(event, "Body", "") or "")
        professor = _parse_professor_from_body(body)
        building = _parse_building_from_body(body)
        candidates.append((subject, start_time, end_time, professor, building))

    for target_variant in target_variants:
        info = _select_event_for_timestamp(target_variant, candidates)
        if info:
            return info

    return None


def _find_outlook_class_for_timestamp(
    target_time: datetime, lookback_minutes: int = 180, lookahead_minutes: int = 180
) -> Optional[str]:
    info = _find_outlook_event_info_for_timestamp(target_time, lookback_minutes, lookahead_minutes)
    return info.class_name if info else None


def _ensure_aware_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value


def _parse_graph_datetime(value: str, timezone_name: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        if timezone_name and timezone_name.upper() in {"UTC", "COORDINATED UNIVERSAL TIME"}:
            parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _graph_authority(config: CalendarRenameConfig) -> str:
    tenant = config.graph_tenant_id.strip() or "consumers"
    return f"https://login.microsoftonline.com/{tenant}"


def _graph_token_cache_path(config: CalendarRenameConfig) -> Path:
    configured = (config.graph_token_cache_path or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".lecture_transcriber" / "graph_token_cache.json"


def _load_msal():
    try:
        import msal
    except ImportError as exc:
        raise RuntimeError("Microsoft Graph device-code auth requires msal. Install with `pip install msal`.") from exc
    return msal


def _acquire_graph_token_client_credentials(config: CalendarRenameConfig) -> str:
    if not config.graph_tenant_id:
        raise RuntimeError("calendar_rename.graph_tenant_id is required for Graph client_credentials auth.")
    if not config.graph_client_id:
        raise RuntimeError("calendar_rename.graph_client_id is required for Graph client_credentials auth.")
    if not config.graph_client_secret:
        raise RuntimeError("calendar_rename.graph_client_secret is required for Graph client_credentials auth.")

    token_url = f"https://login.microsoftonline.com/{config.graph_tenant_id}/oauth2/v2.0/token"
    payload = urlencode(
        {
            "client_id": config.graph_client_id,
            "client_secret": config.graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    request = Request(token_url, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to acquire Microsoft Graph token: {exc}") from exc

    token = str(data.get("access_token", "")).strip()
    if not token:
        raise RuntimeError("Failed to acquire Microsoft Graph token: access_token missing in response.")
    return token


def _acquire_graph_token_device_code(config: CalendarRenameConfig, interactive: bool) -> str:
    if not config.graph_client_id:
        raise RuntimeError("calendar_rename.graph_client_id is required for Graph device_code auth.")

    msal = _load_msal()
    cache_path = _graph_token_cache_path(config)
    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        try:
            cache.deserialize(cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"Graph token cache is invalid at {cache_path}. Delete it and run --graph-login again."
            ) from exc

    app = msal.PublicClientApplication(
        client_id=config.graph_client_id,
        authority=_graph_authority(config),
        token_cache=cache,
    )
    accounts = app.get_accounts()
    token_result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0]) if accounts else None

    if token_result is None and interactive:
        flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(
                flow.get("error_description", "Failed to start Graph device-code authentication flow.")
            )
        print(flow.get("message", "Complete device-code sign-in to continue."))
        token_result = app.acquire_token_by_device_flow(flow)

    if token_result is None:
        raise RuntimeError(
            "No cached Graph token available. Run `python -m lecture_transcriber --config <path> --graph-login` first."
        )

    access_token = str(token_result.get("access_token", "")).strip()
    if not access_token:
        raise RuntimeError(token_result.get("error_description", "Failed to acquire Graph access token."))

    if cache.has_state_changed:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(cache.serialize(), encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Failed to persist Graph token cache to {cache_path}: {exc}") from exc

    return access_token


def _graph_endpoint_for_calendar(config: CalendarRenameConfig, delegated: bool) -> str:
    if delegated:
        mailbox = (config.graph_mailbox_user or "").strip()
        if mailbox:
            return f"https://graph.microsoft.com/v1.0/users/{mailbox}/calendarView"
        return "https://graph.microsoft.com/v1.0/me/calendarView"

    mailbox = (config.graph_mailbox_user or "").strip()
    if not mailbox:
        raise RuntimeError("calendar_rename.graph_mailbox_user is required for Graph client_credentials auth.")
    return f"https://graph.microsoft.com/v1.0/users/{mailbox}/calendarView"


def _find_graph_event_info_for_timestamp(
    target_time: datetime, lookback_minutes: int, lookahead_minutes: int, config: CalendarRenameConfig
) -> Optional[CalendarEventInfo]:
    auth_mode = (config.graph_auth_mode or "device_code").strip().lower()
    if auth_mode == "client_credentials":
        access_token = _acquire_graph_token_client_credentials(config)
        delegated = False
    elif auth_mode == "device_code":
        access_token = _acquire_graph_token_device_code(config, interactive=False)
        delegated = True
    else:
        raise RuntimeError(
            f"Unsupported calendar_rename.graph_auth_mode {config.graph_auth_mode!r}. "
            "Use 'device_code' or 'client_credentials'."
        )

    target = _ensure_aware_local(target_time)
    window_start = target - timedelta(minutes=lookback_minutes)
    window_end = target + timedelta(minutes=lookahead_minutes)

    query = urlencode(
        {
            "startDateTime": window_start.isoformat(),
            "endDateTime": window_end.isoformat(),
            "$select": "subject,start,end,body",
            "$top": "200",
        }
    )
    events_url = f"{_graph_endpoint_for_calendar(config, delegated=delegated)}?{query}"
    request = Request(events_url, method="GET")
    request.add_header("Authorization", f"Bearer {access_token}")
    request.add_header("Accept", "application/json")
    request.add_header("Prefer", 'outlook.timezone="UTC"')

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to query Microsoft Graph calendar events: {exc}") from exc

    candidates: list[_EventTuple] = []
    for event in payload.get("value", []):
        subject = str(event.get("subject", "") or "").strip()
        if not subject:
            continue
        start = event.get("start") or {}
        end = event.get("end") or {}
        start_time = _parse_graph_datetime(str(start.get("dateTime", "")), start.get("timeZone"))
        end_time = _parse_graph_datetime(str(end.get("dateTime", "")), end.get("timeZone"))
        if start_time is None or end_time is None:
            continue
        body_content = str((event.get("body") or {}).get("content", "") or "")
        professor = _parse_professor_from_body(body_content)
        building = _parse_building_from_body(body_content)
        candidates.append((subject, start_time, end_time, professor, building))
    return _select_event_for_timestamp(target, candidates)


def _find_graph_class_for_timestamp(
    target_time: datetime, lookback_minutes: int, lookahead_minutes: int, config: CalendarRenameConfig
) -> Optional[str]:
    info = _find_graph_event_info_for_timestamp(target_time, lookback_minutes, lookahead_minutes, config)
    return info.class_name if info else None

def prime_graph_login(config: CalendarRenameConfig) -> None:
    _acquire_graph_token_device_code(config, interactive=True)


def _graph_is_configured(config: CalendarRenameConfig) -> bool:
    auth_mode = (config.graph_auth_mode or "device_code").strip().lower()
    client_id = (config.graph_client_id or "").strip()
    is_placeholder = client_id.lower() in PLACEHOLDER_CLIENT_IDS
    if auth_mode == "device_code":
        return bool(client_id) and not is_placeholder
    if auth_mode == "client_credentials":
        return bool(
            config.graph_tenant_id and client_id and not is_placeholder and config.graph_client_secret and config.graph_mailbox_user
        )
    return False


def find_class_info_for_timestamp(
    target_time: datetime, config: CalendarRenameConfig, lookback_minutes: int = 180, lookahead_minutes: int = 180
) -> Optional[CalendarEventInfo]:
    """Return full event info (class name + professor) for the best matching calendar event."""
    provider = (config.provider or "auto").strip().lower()
    auto_mode = provider == "auto"
    if provider == "auto":
        provider = "graph" if _graph_is_configured(config) else "outlook"
    if provider == "outlook":
        return _find_outlook_event_info_for_timestamp(
            target_time,
            lookback_minutes=lookback_minutes,
            lookahead_minutes=lookahead_minutes,
        )
    if provider == "graph":
        try:
            return _find_graph_event_info_for_timestamp(
                target_time,
                lookback_minutes=lookback_minutes,
                lookahead_minutes=lookahead_minutes,
                config=config,
            )
        except RuntimeError:
            if not auto_mode:
                raise
            return _find_outlook_event_info_for_timestamp(
                target_time,
                lookback_minutes=lookback_minutes,
                lookahead_minutes=lookahead_minutes,
            )
    raise RuntimeError(f"Unsupported calendar_rename.provider '{config.provider}'. Use 'graph', 'outlook', or 'auto'.")


def find_class_for_timestamp(
    target_time: datetime, config: CalendarRenameConfig, lookback_minutes: int = 180, lookahead_minutes: int = 180
) -> Optional[str]:
    info = find_class_info_for_timestamp(target_time, config, lookback_minutes, lookahead_minutes)
    return info.class_name if info else None
