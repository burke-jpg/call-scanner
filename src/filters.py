"""Filter logic for call records."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD string to datetime (UTC midnight)."""
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def parse_time(time_str: str) -> tuple[int, int]:
    """Parse HH:MM string to (hour, minute) tuple."""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])


def matches_date_range(
    timestamp: str,
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> bool:
    """Check if a timestamp falls within the specified date range.

    Args:
        timestamp: ISO format timestamp from the call record.
        date: Single date filter (YYYY-MM-DD). Matches entire day.
        date_from: Start of date range (inclusive).
        date_to: End of date range (inclusive, entire day).
    """
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        logger.warning("Could not parse timestamp: %s", timestamp)
        return False

    if date:
        target = parse_date(date)
        return dt.date() == target.date()

    if date_from or date_to:
        if date_from:
            start = parse_date(date_from)
            if dt.date() < start.date():
                return False
        if date_to:
            end = parse_date(date_to)
            if dt.date() > end.date():
                return False
        return True

    # No date filter = match all
    return True


def matches_time_range(
    timestamp: str,
    time_from: str | None = None,
    time_to: str | None = None,
) -> bool:
    """Check if a timestamp falls within a time-of-day window.

    Args:
        timestamp: ISO format timestamp.
        time_from: Start time HH:MM (inclusive).
        time_to: End time HH:MM (inclusive).
    """
    if not time_from and not time_to:
        return True

    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False

    call_minutes = dt.hour * 60 + dt.minute

    if time_from:
        h, m = parse_time(time_from)
        if call_minutes < h * 60 + m:
            return False
    if time_to:
        h, m = parse_time(time_to)
        if call_minutes > h * 60 + m:
            return False

    return True


def matches_agent(record: dict, agent_filter: str | None) -> bool:
    """Case-insensitive partial match on agent name."""
    if not agent_filter:
        return True
    agent_name = record.get("agent_name", "") or ""
    return agent_filter.lower() in agent_name.lower()


def matches_client(record: dict, client_filter: str | None) -> bool:
    """Case-insensitive partial match on contact/client name."""
    if not client_filter:
        return True
    contact_name = record.get("contact_name", "") or ""
    return client_filter.lower() in contact_name.lower()


def matches_direction(record: dict, direction_filter: str | None) -> bool:
    """Case-insensitive exact match on call direction (inbound/outbound)."""
    if not direction_filter:
        return True
    return record.get("direction", "").lower() == direction_filter.lower()


def matches_duration(
    record: dict,
    duration_min: int | None = None,
    duration_max: int | None = None,
) -> bool:
    """Check if a call's duration falls within the specified range.

    Args:
        record: Call record with 'duration' field (seconds).
        duration_min: Minimum duration in seconds (inclusive).
        duration_max: Maximum duration in seconds (inclusive).
    """
    if duration_min is None and duration_max is None:
        return True

    duration = record.get("duration", 0)
    if not isinstance(duration, (int, float)):
        try:
            duration = int(duration)
        except (ValueError, TypeError):
            return False

    if duration_min is not None and duration < duration_min:
        return False
    if duration_max is not None and duration > duration_max:
        return False
    return True


def matches_phone(record: dict, phone_filter: str | None) -> bool:
    """Match on phone_from or phone_to (partial, digits only)."""
    if not phone_filter:
        return True
    # Strip to digits only for comparison
    digits = "".join(c for c in phone_filter if c.isdigit())
    phone_from = "".join(c for c in (record.get("phone_from", "") or "") if c.isdigit())
    phone_to = "".join(c for c in (record.get("phone_to", "") or "") if c.isdigit())
    return digits in phone_from or digits in phone_to


def apply_filters(
    records: list[dict],
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    time_from: str | None = None,
    time_to: str | None = None,
    agent: str | None = None,
    client: str | None = None,
    phone: str | None = None,
    direction: str | None = None,
    duration_min: int | None = None,
    duration_max: int | None = None,
) -> list[dict]:
    """Apply all filters to a list of call records.

    Returns only records that pass ALL specified filters.
    """
    filtered = []
    for record in records:
        ts = record.get("timestamp", "")
        if not matches_date_range(ts, date, date_from, date_to):
            continue
        if not matches_time_range(ts, time_from, time_to):
            continue
        if not matches_agent(record, agent):
            continue
        if not matches_client(record, client):
            continue
        if not matches_phone(record, phone):
            continue
        if not matches_direction(record, direction):
            continue
        if not matches_duration(record, duration_min, duration_max):
            continue
        filtered.append(record)

    logger.info("Filtered %d → %d records", len(records), len(filtered))
    return filtered
