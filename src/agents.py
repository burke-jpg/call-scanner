"""Agent discovery and caching.

Scans recent Twilio calls to extract all unique agent names from
client: URIs. Caches results in agents.json with a configurable TTL.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from .twilio_client import TwilioClient, extract_agent

logger = logging.getLogger(__name__)

_AGENTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents.json")
_DEFAULT_TTL_HOURS = 24


def load_agents() -> list[str] | None:
    """Load cached agent list from agents.json.

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

    agents = data.get("agents", [])
    return sorted(agents) if agents else None


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
    """Scan recent Twilio calls to discover all unique agent names.

    Args:
        twilio: Initialized TwilioClient instance.
        days: Number of days to look back (default 14).

    Returns:
        Sorted list of unique agent first names.
    """
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=days)

    raw_calls = twilio.get_calls(
        date_from=start.strftime("%Y-%m-%d"),
        date_to=end.strftime("%Y-%m-%d"),
    )

    agents = set()
    for call in raw_calls:
        to = call.get("to", "")
        name = extract_agent(to)
        if name:
            agents.add(name)

    result = sorted(agents)
    logger.info("Discovered %d agents from %d days of calls: %s", len(result), days, result)
    return result


def save_agents(agent_list: list[str]) -> None:
    """Write agent list to agents.json."""
    data = {
        "version": 1,
        "updated": datetime.now(tz=timezone.utc).isoformat(),
        "agents": sorted(agent_list),
    }
    with open(_AGENTS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved %d agents to agents.json", len(agent_list))
