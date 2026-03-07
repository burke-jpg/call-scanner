"""Natural language query parser for recording retrieval.

Converts free text like "George Tuesday morning" into structured filters.

Pipeline (priority order):
  1. Direction tokens (inbound/outbound)
  2. Limit tokens (last N / first N)
  3. Agent names (from known list)
  4. Time-of-day (morning/afternoon/evening)
  5. Relative dates (today/yesterday/weekdays/this week/last week)
  6. Remainder → client filter
"""

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta


# Stopwords removed before client extraction
STOPWORDS = frozenset({
    "calls", "call", "recordings", "recording", "from", "the", "a", "an",
    "with", "by", "give", "me", "get", "show", "all", "my", "of", "for",
    "on", "at", "to", "and", "in", "out",
})

# Default known agents (overridable via KNOWN_AGENTS env var)
DEFAULT_AGENTS = "george,sara,omar,danny,ian,chris,burke,william"

# Day-of-week name → weekday number (Monday=0)
WEEKDAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

TIME_OF_DAY = {
    "morning": ("06:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening": ("17:00", "22:00"),
    "night": ("17:00", "23:59"),
}

DIRECTION_TOKENS = {
    "inbound": "inbound",
    "outbound": "outbound",
}


@dataclass
class ParsedQuery:
    """Structured result from parsing a natural language query."""

    agent: str | None = None
    date: str | None = None          # Single date YYYY-MM-DD
    date_from: str | None = None     # Range start
    date_to: str | None = None       # Range end
    time_from: str | None = None     # HH:MM
    time_to: str | None = None       # HH:MM
    client: str | None = None
    phone: str | None = None
    direction: str | None = None     # inbound / outbound
    limit: int | None = None         # Max results
    limit_from: str = "tail"         # "tail" (last N) or "head" (first N)
    raw_query: str = ""

    def has_filters(self) -> bool:
        """Return True if any filter is set."""
        return any([
            self.agent, self.date, self.date_from, self.date_to,
            self.time_from, self.time_to, self.client, self.phone,
            self.direction,
        ])

    def summary(self) -> str:
        """Human-readable summary of what was parsed."""
        parts = []
        if self.agent:
            parts.append(f"agent={self.agent}")
        if self.date:
            parts.append(f"date={self.date}")
        if self.date_from and self.date_to:
            parts.append(f"range={self.date_from}..{self.date_to}")
        elif self.date_from:
            parts.append(f"from={self.date_from}")
        elif self.date_to:
            parts.append(f"to={self.date_to}")
        if self.time_from and self.time_to:
            parts.append(f"time={self.time_from}-{self.time_to}")
        elif self.time_from:
            parts.append(f"after={self.time_from}")
        elif self.time_to:
            parts.append(f"before={self.time_to}")
        if self.client:
            parts.append(f"client={self.client}")
        if self.phone:
            parts.append(f"phone={self.phone}")
        if self.direction:
            parts.append(f"dir={self.direction}")
        if self.limit:
            parts.append(f"{self.limit_from} {self.limit}")
        return ", ".join(parts) if parts else "no filters"


def get_known_agents() -> list[str]:
    """Load known agent names from env or defaults."""
    raw = os.getenv("KNOWN_AGENTS", DEFAULT_AGENTS)
    return [a.strip().lower() for a in raw.split(",") if a.strip()]


def _most_recent_weekday(target_weekday: int, ref: date) -> date:
    """Find the most recent occurrence of a weekday on or before ref."""
    days_back = (ref.weekday() - target_weekday) % 7
    if days_back == 0:
        return ref  # Today is that day
    return ref - timedelta(days=days_back)


def _previous_week_weekday(target_weekday: int, ref: date) -> date:
    """Find the occurrence of a weekday in the previous week."""
    # Go to most recent, then back 7 more days
    most_recent = _most_recent_weekday(target_weekday, ref)
    if most_recent == ref:
        return ref - timedelta(days=7)
    # If most_recent is in the current week, go back 7
    return most_recent - timedelta(days=7)


def parse_query(text: str, reference_date: date | None = None) -> ParsedQuery:
    """Parse a natural language query into structured filters.

    Args:
        text: Free-text query like "George Tuesday morning".
        reference_date: Date for resolving relative terms (defaults to today).

    Returns:
        ParsedQuery with extracted filters.
    """
    if not text or not text.strip():
        return ParsedQuery(raw_query=text or "")

    ref = reference_date or date.today()
    result = ParsedQuery(raw_query=text)
    known_agents = get_known_agents()

    # Normalize: lowercase, strip extra whitespace
    tokens = text.lower().strip().split()
    consumed = set()  # Indices of consumed tokens

    # --- Pass 1: Direction ---
    for i, tok in enumerate(tokens):
        if tok in DIRECTION_TOKENS:
            result.direction = DIRECTION_TOKENS[tok]
            consumed.add(i)
            break

    # --- Pass 2: Limits ("last N" / "first N") ---
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue
        if tok in ("last", "first", "latest", "recent") and i + 1 < len(tokens):
            next_tok = tokens[i + 1]
            if next_tok.isdigit():
                result.limit = int(next_tok)
                result.limit_from = "tail" if tok in ("last", "latest", "recent") else "head"
                consumed.add(i)
                consumed.add(i + 1)
                break

    # --- Pass 3: Agent names ---
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue
        if tok in known_agents:
            result.agent = tok
            consumed.add(i)
            break

    # --- Pass 4: Time of day ---
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue
        if tok in TIME_OF_DAY:
            result.time_from, result.time_to = TIME_OF_DAY[tok]
            consumed.add(i)
            break

    # --- Pass 5: Dates ---
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue

        # "today"
        if tok == "today":
            result.date = ref.isoformat()
            consumed.add(i)
            break

        # "yesterday"
        if tok == "yesterday":
            result.date = (ref - timedelta(days=1)).isoformat()
            consumed.add(i)
            break

        # "this week" → Monday through ref
        if tok == "this" and i + 1 < len(tokens) and tokens[i + 1] == "week":
            monday = ref - timedelta(days=ref.weekday())
            result.date_from = monday.isoformat()
            result.date_to = ref.isoformat()
            consumed.add(i)
            consumed.add(i + 1)
            break

        # "last week" → previous Monday–Sunday
        if tok == "last" and i in consumed:
            continue
        if tok == "last" and i + 1 < len(tokens) and tokens[i + 1] == "week":
            this_monday = ref - timedelta(days=ref.weekday())
            last_monday = this_monday - timedelta(days=7)
            last_sunday = last_monday + timedelta(days=6)
            result.date_from = last_monday.isoformat()
            result.date_to = last_sunday.isoformat()
            consumed.add(i)
            consumed.add(i + 1)
            break

        # "last {weekday}" → previous week's occurrence
        if tok == "last" and i + 1 < len(tokens) and tokens[i + 1] in WEEKDAY_MAP:
            target = WEEKDAY_MAP[tokens[i + 1]]
            result.date = _previous_week_weekday(target, ref).isoformat()
            consumed.add(i)
            consumed.add(i + 1)
            break

        # Bare weekday name → most recent occurrence
        if tok in WEEKDAY_MAP:
            target = WEEKDAY_MAP[tok]
            result.date = _most_recent_weekday(target, ref).isoformat()
            consumed.add(i)
            break

        # ISO date YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", tok):
            result.date = tok
            consumed.add(i)
            break

    # --- Pass 6: Phone numbers ---
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue
        # Looks like a phone number (7+ digits, possibly with + prefix)
        digits = re.sub(r"[^\d]", "", tok)
        if len(digits) >= 7:
            result.phone = tok
            consumed.add(i)
            break

    # --- Pass 7: Remainder → client ---
    remainder = []
    for i, tok in enumerate(tokens):
        if i in consumed:
            continue
        if tok in STOPWORDS:
            continue
        remainder.append(tok)

    if remainder:
        result.client = " ".join(remainder)

    return result
