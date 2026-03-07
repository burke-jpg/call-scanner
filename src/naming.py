"""File naming logic for downloaded recordings.

Pattern: {agent}_{date}_{time}_{dir}_{contact}_{sid}.mp3

Agent-first so files group by handler, then sort chronologically.
Contact is a slugified name when available, or last-10 phone digits.
Direction is abbreviated: in / out.

Examples:
    george_2026-03-06_2005_in_4037761148_af89c.mp3
    sara_2026-03-06_1432_in_sapochnick-law_b3f9a.mp3
    noagent_2026-03-06_0800_in_5551234567_c1d2e.mp3
"""

import re
from datetime import datetime


def slugify(text: str, max_length: int = 20) -> str:
    """Convert text to a URL-safe slug.

    Lowercase, hyphens instead of spaces, strip special chars, truncate.
    """
    if not text:
        return "unknown"
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    if len(text) > max_length:
        # Truncate at word boundary if possible
        truncated = text[:max_length]
        last_hyphen = truncated.rfind("-")
        if last_hyphen > max_length // 2:
            truncated = truncated[:last_hyphen]
        text = truncated.rstrip("-")
    return text or "unknown"


def extract_first_name(full_name: str) -> str:
    """Extract first name from a full name, lowercase."""
    if not full_name:
        return "unknown"
    return full_name.strip().split()[0].lower()


def format_timestamp(iso_timestamp: str) -> tuple[str, str]:
    """Parse ISO timestamp into (date_str, time_str).

    Returns:
        ("2026-03-06", "1432") format tuple.
    """
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%H%M")
    except (ValueError, AttributeError):
        return "0000-00-00", "0000"


def _is_phone_number(text: str) -> bool:
    """Check if text looks like a phone number (mostly digits)."""
    if not text:
        return False
    digits_only = re.sub(r"[^\d]", "", text)
    return len(digits_only) >= 7 and len(digits_only) / max(len(text), 1) > 0.5


def format_contact(contact_name: str) -> str:
    """Format contact for filename: slug if name, last 10 digits if phone."""
    if not contact_name:
        return "unknown"
    if _is_phone_number(contact_name):
        digits = re.sub(r"[^\d]", "", contact_name)
        return digits[-10:]  # Last 10 digits (area + number)
    return slugify(contact_name, max_length=20)


def build_filename(call_record: dict) -> str:
    """Build a structured filename for a recording.

    Format: {agent}_{date}_{time}_{dir}_{contact}_{sid}.mp3

    Agent-first so files sort by handler then chronologically.

    Args:
        call_record: Dict with keys: contact_name, agent_name, timestamp,
                     direction, recording_sid (or call_sid as fallback).
    """
    agent = call_record.get("agent_name", "").strip().lower()
    if not agent:
        agent = "noagent"
    else:
        agent = agent.split()[0]  # First name only

    date_str, time_str = format_timestamp(call_record.get("timestamp", ""))

    direction = call_record.get("direction", "unknown").lower()
    dir_short = {"inbound": "in", "outbound": "out"}.get(direction, "unk")

    contact = format_contact(call_record.get("contact_name", ""))

    # Use recording_sid if available, fall back to call_sid
    sid = call_record.get("recording_sid", call_record.get("call_sid", ""))
    sid_short = sid[-5:] if sid else "00000"

    return f"{agent}_{date_str}_{time_str}_{dir_short}_{contact}_{sid_short}.mp3"
