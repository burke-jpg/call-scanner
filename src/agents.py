"""Agent discovery, lifecycle tracking, and caching.

Scans recent Twilio calls to extract all unique agent names from
client: URIs. Caches results in agents.json with per-agent metadata
(first_seen, last_seen, call_count) and a change log.

v2 format adds lifecycle tracking:
  - Per-agent: first_seen, last_seen, call_count
  - Computed status: active / new / inactive
  - Change log: new arrivals, inactive transitions
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from .twilio_client import TwilioClient, extract_agent

logger = logging.getLogger(__name__)

_AGENTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.json")
_DEFAULT_TTL_HOURS = 24

# Thresholds for agent status computation
ACTIVE_DAYS = 7       # last_seen within N days = active
NEW_AGENT_DAYS = 14   # first_seen within N days AND active = new


def _today_str() -> str:
    """Return today's date as YYYY-MM-DD string (UTC)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def compute_agent_status(
    agent_data: dict,
    reference_date: str | None = None,
) -> str:
    """Compute agent status from their metadata.

    Args:
        agent_data: Dict with first_seen, last_seen, call_count.
        reference_date: YYYY-MM-DD for comparison (defaults to today UTC).

    Returns:
        'active', 'new', or 'inactive'.
    """
    ref = reference_date or _today_str()
    try:
        ref_dt = datetime.strptime(ref, "%Y-%m-%d").date()
    except ValueError:
        ref_dt = datetime.now(tz=timezone.utc).date()

    last_seen = agent_data.get("last_seen", "")
    first_seen = agent_data.get("first_seen", "")

    if not last_seen:
        return "inactive"

    try:
        last_dt = datetime.strptime(last_seen, "%Y-%m-%d").date()
    except ValueError:
        return "inactive"

    days_since_last = (ref_dt - last_dt).days

    if days_since_last > ACTIVE_DAYS:
        return "inactive"

    # Active — check if also "new"
    if first_seen:
        try:
            first_dt = datetime.strptime(first_seen, "%Y-%m-%d").date()
            days_since_first = (ref_dt - first_dt).days
            if days_since_first <= NEW_AGENT_DAYS:
                return "new"
        except ValueError:
            pass

    return "active"


def migrate_v1_to_v2(v1_data: dict) -> dict:
    """Convert v1 agents.json (flat list) to v2 format (per-agent metadata).

    v1: {"version": 1, "updated": "...", "agents": ["sara", "omar", ...]}
    v2: {"version": 2, "updated": "...", "agents": {"sara": {...}, ...}, "changes": [...]}
    """
    updated = v1_data.get("updated", datetime.now(tz=timezone.utc).isoformat())
    agent_list = v1_data.get("agents", [])

    # Extract a date from the updated timestamp for first_seen/last_seen
    try:
        updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        date_str = updated_dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        date_str = _today_str()

    agents_dict = {}
    for name in agent_list:
        agents_dict[name] = {
            "first_seen": date_str,
            "last_seen": date_str,
            "call_count": 0,  # Unknown from v1
        }

    return {
        "version": 2,
        "updated": updated,
        "agents": agents_dict,
        "changes": [],
    }


def load_agents_v2() -> dict | None:
    """Load full v2 agent data from agents.json.

    Handles v1→v2 migration transparently. Returns None if file missing.

    Returns:
        Full v2 data dict, or None if cache missing/unreadable.
    """
    if not os.path.exists(_AGENTS_PATH):
        return None

    try:
        with open(_AGENTS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read agents.json: %s", e)
        return None

    version = data.get("version", 1)

    if version < 2:
        logger.info("Migrating agents.json from v%d to v2", version)
        data = migrate_v1_to_v2(data)
        # Save migrated data
        _write_agents_file(data)

    return data


def load_agents() -> list[str] | None:
    """Load cached agent list from agents.json.

    Backward-compatible interface: returns flat sorted list of names.
    Used by nlp.py for agent name matching.

    Returns:
        Sorted list of agent names, or None if cache is missing or stale.
    """
    if not os.path.exists(_AGENTS_PATH):
        return None

    try:
        with open(_AGENTS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read agents.json: %s", e)
        return None

    if is_stale(data):
        logger.info("agents.json is stale, needs refresh")
        return None

    version = data.get("version", 1)
    if version >= 2:
        agents_dict = data.get("agents", {})
        names = list(agents_dict.keys())
    else:
        names = data.get("agents", [])

    return sorted(names) if names else None


def is_stale(data: dict | None = None) -> bool:
    """Check if the agent cache is older than the configured TTL."""
    if data is None:
        if not os.path.exists(_AGENTS_PATH):
            return True
        try:
            with open(_AGENTS_PATH) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return True

    updated = data.get("updated", "")
    if not updated:
        return True

    try:
        updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True

    ttl_hours = int(os.getenv("AGENT_CACHE_TTL_HOURS", str(_DEFAULT_TTL_HOURS)))
    return datetime.now(tz=timezone.utc) - updated_dt > timedelta(hours=ttl_hours)


def discover_agents(twilio: TwilioClient, days: int = 14) -> list[str]:
    """Scan recent Twilio calls to discover agents and update v2 metadata.

    Updates per-agent first_seen, last_seen, call_count. Detects new
    agents and newly inactive agents, recording changes.

    Args:
        twilio: Initialized TwilioClient instance.
        days: Number of days to look back (default 14).

    Returns:
        Sorted list of all unique agent first names.
    """
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=days)
    today = end.strftime("%Y-%m-%d")

    raw_calls = twilio.get_calls(
        date_from=start.strftime("%Y-%m-%d"),
        date_to=end.strftime("%Y-%m-%d"),
    )

    # Count calls per agent from scan
    scan_counts: dict[str, int] = {}
    scan_last_seen: dict[str, str] = {}
    for call in raw_calls:
        to = call.get("to", "")
        name = extract_agent(to)
        if not name:
            continue
        scan_counts[name] = scan_counts.get(name, 0) + 1
        # Track last seen date from call timestamps
        ts = call.get("start_time", "")
        if ts:
            try:
                call_date = datetime.fromisoformat(
                    ts.replace("Z", "+00:00")
                ).strftime("%Y-%m-%d")
                if call_date > scan_last_seen.get(name, ""):
                    scan_last_seen[name] = call_date
            except (ValueError, AttributeError):
                pass

    # Load existing v2 data (or start fresh)
    existing = load_agents_v2() or {
        "version": 2,
        "updated": "",
        "agents": {},
        "changes": [],
    }

    agents_dict: dict = existing.get("agents", {})
    changes: list = existing.get("changes", [])

    # Detect new agents (in scan but not in existing data)
    for name, count in scan_counts.items():
        if name not in agents_dict:
            # New agent discovered
            first_date = scan_last_seen.get(name, today)
            agents_dict[name] = {
                "first_seen": first_date,
                "last_seen": first_date,
                "call_count": count,
            }
            changes.append({
                "date": today,
                "type": "new",
                "agent": name,
            })
            logger.info("New agent discovered: %s", name)
        else:
            # Update existing agent
            agent = agents_dict[name]
            last = scan_last_seen.get(name, agent.get("last_seen", ""))
            if last > agent.get("last_seen", ""):
                agent["last_seen"] = last
            agent["call_count"] = agent.get("call_count", 0) + count

    # Detect newly inactive agents
    for name, agent in agents_dict.items():
        if name in scan_counts:
            continue  # Active in scan
        status = compute_agent_status(agent, today)
        if status == "inactive":
            # Check if we already logged this transition
            already_logged = any(
                c.get("agent") == name and c.get("type") == "inactive"
                for c in changes[-20:]  # Check recent changes
            )
            if not already_logged:
                changes.append({
                    "date": today,
                    "type": "inactive",
                    "agent": name,
                })
                logger.info("Agent became inactive: %s", name)

    # Merge with DEFAULT_AGENTS so hardcoded agents never disappear
    from .nlp import DEFAULT_AGENTS
    for a in DEFAULT_AGENTS.split(","):
        a = a.strip().lower()
        if a and a not in agents_dict:
            agents_dict[a] = {
                "first_seen": today,
                "last_seen": today,
                "call_count": 0,
            }

    # Save v2 format
    save_agents_v2(agents_dict, changes)

    result = sorted(agents_dict.keys())
    logger.info("Discovered %d agents from %d days of calls: %s", len(result), days, result)
    return result


def get_agent_roster(reference_date: str | None = None) -> dict:
    """Get the full agent roster with computed statuses.

    Returns:
        Dict with 'agents' list and 'recent_changes' list, suitable
        for the /api/agent-roster endpoint.
    """
    data = load_agents_v2()
    if not data:
        return {"agents": [], "recent_changes": []}

    agents_dict = data.get("agents", {})
    changes = data.get("changes", [])
    ref = reference_date or _today_str()

    roster = []
    for name, meta in sorted(agents_dict.items()):
        status = compute_agent_status(meta, ref)
        roster.append({
            "name": name,
            "status": status,
            "first_seen": meta.get("first_seen", ""),
            "last_seen": meta.get("last_seen", ""),
            "call_count": meta.get("call_count", 0),
        })

    # Return last 20 changes, newest first
    recent = sorted(changes, key=lambda c: c.get("date", ""), reverse=True)[:20]

    return {"agents": roster, "recent_changes": recent}


def save_agents_v2(agents_dict: dict, changes: list | None = None) -> None:
    """Write v2 agent data to agents.json."""
    data = {
        "version": 2,
        "updated": datetime.now(tz=timezone.utc).isoformat(),
        "agents": agents_dict,
        "changes": changes or [],
    }
    _write_agents_file(data)
    logger.info("Saved %d agents to agents.json (v2)", len(agents_dict))


def save_agents(agent_list: list[str]) -> None:
    """Write agent list to agents.json (backward-compatible v2 save).

    Converts flat list to v2 format, preserving existing metadata
    if agents.json already has v2 data.
    """
    existing = load_agents_v2()
    today = _today_str()

    if existing:
        agents_dict = existing.get("agents", {})
        changes = existing.get("changes", [])
        # Add any new agents from the list
        for name in agent_list:
            name = name.lower().strip()
            if name and name not in agents_dict:
                agents_dict[name] = {
                    "first_seen": today,
                    "last_seen": today,
                    "call_count": 0,
                }
    else:
        agents_dict = {}
        changes = []
        for name in agent_list:
            name = name.lower().strip()
            if name:
                agents_dict[name] = {
                    "first_seen": today,
                    "last_seen": today,
                    "call_count": 0,
                }

    save_agents_v2(agents_dict, changes)


def _write_agents_file(data: dict) -> None:
    """Write data to agents.json file."""
    with open(_AGENTS_PATH, "w") as f:
        json.dump(data, f, indent=2)
