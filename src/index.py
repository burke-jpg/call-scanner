"""Metadata index manager for downloaded recordings.

Maintains a JSON sidecar (index.json) alongside recordings so files
are searchable by any metric: agent, client, date, time, direction.

The index is keyed by filename for O(1) lookup and is only updated
after successful downloads (never on --dry-run or --list).
"""

import json
import os
from datetime import datetime, timezone


INDEX_FILENAME = "index.json"


def _empty_index() -> dict:
    """Return a fresh empty index structure."""
    return {
        "version": 1,
        "updated_at": "",
        "recordings": {},
    }


def load_index(directory: str) -> dict:
    """Load the index from disk, or return an empty one."""
    path = os.path.join(directory, INDEX_FILENAME)
    if not os.path.exists(path):
        return _empty_index()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("recordings"), dict):
            return _empty_index()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_index()


def save_index(directory: str, index: dict) -> None:
    """Write the index to disk."""
    index["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
    path = os.path.join(directory, INDEX_FILENAME)
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def add_entry(
    index: dict,
    filename: str,
    relative_path: str,
    call_record: dict,
    recording_sid: str,
    size_bytes: int = 0,
) -> None:
    """Add a recording entry to the index.

    Args:
        index: The index dict (mutated in place).
        filename: Base filename (e.g. george_2026-03-06_2005_in_...).
        relative_path: Path relative to recordings dir (e.g. 2026-03-06/filename).
        call_record: The unified call record dict.
        recording_sid: Twilio recording SID.
        size_bytes: File size after download.
    """
    from .naming import extract_first_name, format_timestamp

    agent = call_record.get("agent_name", "")
    if agent:
        agent = extract_first_name(agent)

    date_str, time_str = format_timestamp(call_record.get("timestamp", ""))

    index["recordings"][filename] = {
        "path": relative_path,
        "agent": agent,
        "contact_name": call_record.get("contact_name", ""),
        "date": date_str,
        "time": time_str,
        "direction": call_record.get("direction", "unknown"),
        "duration": call_record.get("duration", 0),
        "phone_from": call_record.get("phone_from", ""),
        "phone_to": call_record.get("phone_to", ""),
        "call_sid": call_record.get("call_sid", ""),
        "recording_sid": recording_sid,
        "downloaded_at": datetime.now(tz=timezone.utc).isoformat(),
        "size_bytes": size_bytes,
    }


def search_index(
    index: dict,
    agent: str | None = None,
    date: str | None = None,
    direction: str | None = None,
    client: str | None = None,
) -> list[dict]:
    """Search the index for matching recordings.

    Returns list of matching entry dicts with filename added.
    """
    results = []
    for filename, entry in index.get("recordings", {}).items():
        if agent and entry.get("agent", "").lower() != agent.lower():
            continue
        if date and entry.get("date") != date:
            continue
        if direction and entry.get("direction", "").lower() != direction.lower():
            continue
        if client:
            contact = entry.get("contact_name", "").lower()
            if client.lower() not in contact:
                continue
        results.append({**entry, "filename": filename})
    return results
