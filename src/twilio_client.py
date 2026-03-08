"""Twilio client for querying calls, extracting agents, and downloading recordings.

Architecture: Twilio-first. All call data comes directly from Twilio.
Agent identification via Flex call leg URIs (client:{agent_email_encoded}).
No GHL dependency.
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from tqdm import tqdm
from twilio.rest import Client as TwilioSDK

from .naming import build_filename, format_timestamp

logger = logging.getLogger(__name__)

# Maximum seconds between inbound and agent leg start times for pairing
PAIR_WINDOW_SECONDS = 30


def extract_agent(to_field: str) -> str:
    """Extract agent first name from Twilio Flex call leg 'to' field.

    Twilio Flex routes calls to agents using client URIs:
        client:george_40jumpcontact_2Ecom  ->  george
        client:anthony                      ->  anthony

    Encoding: _XX is a hex-escaped character (_40 = @, _2E = .)

    Args:
        to_field: The 'to' value from a Twilio call leg.

    Returns:
        Lowercase agent first name, or empty string if not a client URI.
    """
    if not to_field:
        return ""

    # Must start with client:
    if not to_field.lower().startswith("client:"):
        return ""

    name = to_field[7:]  # Strip "client:" prefix

    # Decode _XX hex sequences -> actual characters
    name = re.sub(r"_([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), name)

    # Take everything before @ (email -> first name)
    if "@" in name:
        name = name.split("@")[0]

    return name.lower().strip()


def normalize_phone(phone: str) -> str:
    """Normalize a phone number to digits only (strip +, spaces, dashes)."""
    if not phone:
        return ""
    return re.sub(r"[^\d]", "", phone)


def parse_iso(ts: str) -> datetime | None:
    """Parse ISO timestamp, returning None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class TwilioClient:
    """Client for querying Twilio calls, resolving agents, and downloading recordings."""

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
    ):
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")
        if not self.account_sid:
            raise ValueError("TWILIO_ACCOUNT_SID is required")
        if not self.auth_token:
            raise ValueError("TWILIO_AUTH_TOKEN is required")
        self.client = TwilioSDK(self.account_sid, self.auth_token)

    # ------------------------------------------------------------------ #
    #  Call querying                                                       #
    # ------------------------------------------------------------------ #

    def get_calls(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        """Query Twilio for all call legs in a date range.

        Args:
            date_from: Start date YYYY-MM-DD (defaults to today).
            date_to: End date YYYY-MM-DD (defaults to date_from).

        Returns:
            List of raw call dicts with sid, from_, to, direction,
            start_time, duration, status.
        """
        if not date_from:
            date_from = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if not date_to:
            date_to = date_from

        start = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = (
            datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            + timedelta(days=1)
        )

        try:
            calls = self.client.calls.list(
                start_time_after=start,
                start_time_before=end,
                limit=500,
            )
        except Exception as e:
            logger.error("Failed to query Twilio calls: %s", e)
            return []

        results = []
        for c in calls:
            results.append({
                "sid": c.sid,
                "from_": c._from or "",
                "to": c.to or "",
                "direction": c.direction or "",
                "start_time": c.start_time.isoformat() if c.start_time else "",
                "duration": int(c.duration) if c.duration else 0,
                "status": c.status or "",
            })

        logger.info("Twilio returned %d call legs", len(results))
        return results

    # ------------------------------------------------------------------ #
    #  Call leg pairing                                                    #
    # ------------------------------------------------------------------ #

    def pair_call_legs(self, raw_calls: list[dict]) -> list[dict]:
        """Pair inbound caller legs with outbound-api agent legs.

        Twilio Flex creates two legs per answered call:
          1. Inbound:  from=caller, to=JC_trunk, direction=inbound
          2. Agent:    from=JC_trunk, to=client:{agent}, direction=outbound-api

        We match by: same JC trunk number + start_time within PAIR_WINDOW_SECONDS.

        Returns:
            List of unified call records compatible with the filter/naming
            interfaces: call_sid, contact_name, agent_name, timestamp,
            direction, phone_from, phone_to.
        """
        agent_legs = []
        inbound_legs = []

        for call in raw_calls:
            to = call.get("to", "")
            direction = call.get("direction", "")

            if "client:" in to.lower():
                agent_legs.append(call)
            elif direction == "inbound":
                inbound_legs.append(call)

        logger.info(
            "Call legs: %d agent, %d inbound, %d other",
            len(agent_legs),
            len(inbound_legs),
            len(raw_calls) - len(agent_legs) - len(inbound_legs),
        )

        # Index inbound legs by JC trunk number for fast lookup
        inbound_by_trunk: dict[str, list[dict]] = {}
        for leg in inbound_legs:
            trunk = normalize_phone(leg.get("to", ""))
            if trunk:
                inbound_by_trunk.setdefault(trunk, []).append(leg)

        paired_inbound_sids: set[str] = set()
        records = []
        paired_count = 0

        for agent_leg in agent_legs:
            agent_name = extract_agent(agent_leg.get("to", ""))
            trunk = normalize_phone(agent_leg.get("from_", ""))
            agent_time = parse_iso(agent_leg.get("start_time", ""))

            if not trunk or not agent_time:
                records.append(_build_record(agent_leg, None, agent_name))
                continue

            # Find closest inbound leg on same trunk within window
            candidates = inbound_by_trunk.get(trunk, [])
            best_match = None
            best_delta = timedelta(seconds=PAIR_WINDOW_SECONDS + 1)

            for inbound in candidates:
                if inbound["sid"] in paired_inbound_sids:
                    continue
                inbound_time = parse_iso(inbound.get("start_time", ""))
                if not inbound_time:
                    continue
                delta = abs(agent_time - inbound_time)
                if delta < best_delta:
                    best_delta = delta
                    best_match = inbound

            if best_match and best_delta <= timedelta(seconds=PAIR_WINDOW_SECONDS):
                paired_inbound_sids.add(best_match["sid"])
                records.append(_build_record(agent_leg, best_match, agent_name))
                paired_count += 1
            else:
                records.append(_build_record(agent_leg, None, agent_name))

        # Include unmatched inbound legs (unanswered calls, IVR, etc.)
        for leg in inbound_legs:
            if leg["sid"] not in paired_inbound_sids:
                records.append(_build_record(None, leg, ""))

        unmatched_agent = len(agent_legs) - paired_count
        unmatched_inbound = len(inbound_legs) - len(paired_inbound_sids)
        logger.info(
            "Pairing: %d matched, %d unmatched agent, %d unmatched inbound => %d records",
            paired_count,
            unmatched_agent,
            unmatched_inbound,
            len(records),
        )

        return records

    # ------------------------------------------------------------------ #
    #  Recording methods                                                   #
    # ------------------------------------------------------------------ #

    def get_recordings_for_call(self, call_sid: str) -> list[dict]:
        """Fetch all recording SIDs for a given call SID."""
        if not call_sid:
            return []

        try:
            recordings = self.client.recordings.list(call_sid=call_sid, limit=20)
        except Exception as e:
            logger.error("Failed to fetch recordings for %s: %s", call_sid, e)
            return []

        results = []
        for rec in recordings:
            results.append({
                "recording_sid": rec.sid,
                "duration": rec.duration,
                "date_created": (
                    rec.date_created.isoformat() if rec.date_created else ""
                ),
            })

        logger.info("Found %d recording(s) for call %s", len(results), call_sid)
        return results

    def download_recording(self, recording_sid: str, output_path: str) -> bool:
        """Download a single recording as MP3."""
        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"
            f"/Recordings/{recording_sid}.mp3"
        )

        try:
            resp = requests.get(
                url,
                auth=(self.account_sid, self.auth_token),
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_kb = os.path.getsize(output_path) / 1024
            logger.info("Downloaded %s (%.1f KB)", output_path, size_kb)
            return True

        except requests.exceptions.RequestException as e:
            logger.error("Failed to download recording %s: %s", recording_sid, e)
            return False

    def bulk_download(
        self,
        call_records: list[dict],
        output_dir: str = "./recordings",
    ) -> dict:
        """Download recordings for all matched calls.

        Tries both call_sid (inbound leg) and agent_sid (agent leg) when
        looking for recordings, since Twilio may attach the recording to
        either leg.

        Files are saved into date-based subfolders: {output_dir}/{YYYY-MM-DD}/

        Returns:
            Dict with download stats and index_entries for metadata tracking.
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        stats = {"downloaded": 0, "skipped": 0, "failed": 0, "no_recording": 0}
        download_queue = []  # (rec_sid, output_path, filename, date_str, record)

        logger.info("Resolving recordings for %d calls...", len(call_records))
        for record in tqdm(call_records, desc="Finding recordings", unit="call"):
            call_sid = record.get("call_sid", "")
            agent_sid = record.get("agent_sid", "")

            if not call_sid and not agent_sid:
                stats["skipped"] += 1
                continue

            # Try primary SID first, then fallback to agent SID
            recordings = []
            if call_sid:
                recordings = self.get_recordings_for_call(call_sid)
            if not recordings and agent_sid:
                recordings = self.get_recordings_for_call(agent_sid)

            if not recordings:
                stats["no_recording"] += 1
                continue

            # Extract date for subfolder
            date_str, _ = format_timestamp(record.get("timestamp", ""))
            if not date_str:
                date_str = "unknown"

            for rec in recordings:
                enriched = {**record, "recording_sid": rec["recording_sid"]}
                filename = build_filename(enriched)
                output_path = os.path.join(output_dir, date_str, filename)

                if os.path.exists(output_path):
                    logger.info("Already exists, skipping: %s", filename)
                    stats["skipped"] += 1
                    continue

                download_queue.append((
                    rec["recording_sid"], output_path, filename,
                    date_str, record,
                ))

        if not download_queue:
            logger.info("No new recordings to download")
            return stats

        logger.info("Downloading %d recording(s)...", len(download_queue))
        index_entries = []
        for rec_sid, output_path, filename, date_str, record in tqdm(
            download_queue, desc="Downloading", unit="file"
        ):
            success = self.download_recording(rec_sid, output_path)
            if success:
                stats["downloaded"] += 1
                size_bytes = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                index_entries.append({
                    "filename": filename,
                    "relative_path": os.path.join(date_str, filename),
                    "record": record,
                    "recording_sid": rec_sid,
                    "size_bytes": size_bytes,
                })
            else:
                stats["failed"] += 1

        stats["index_entries"] = index_entries
        return stats


# ------------------------------------------------------------------ #
#  Module-level helpers                                                #
# ------------------------------------------------------------------ #


def _build_record(
    agent_leg: dict | None,
    inbound_leg: dict | None,
    agent_name: str,
) -> dict:
    """Build a unified call record from paired legs.

    For recording downloads, we store both SIDs so bulk_download can
    try both when searching for the recording.
    """
    if inbound_leg and agent_leg:
        # Paired call: caller info from inbound, agent from agent leg
        return {
            "call_sid": inbound_leg["sid"],
            "agent_sid": agent_leg["sid"],
            "contact_name": inbound_leg.get("from_", "Unknown"),
            "agent_name": agent_name,
            "timestamp": inbound_leg.get("start_time", ""),
            "direction": "inbound",
            "phone_from": inbound_leg.get("from_", ""),
            "phone_to": inbound_leg.get("to", ""),
            "duration": max(
                inbound_leg.get("duration", 0),
                agent_leg.get("duration", 0),
            ),
            "status": inbound_leg.get("status", ""),
        }
    elif agent_leg:
        # Agent leg only (unmatched)
        return {
            "call_sid": agent_leg["sid"],
            "agent_sid": agent_leg["sid"],
            "contact_name": agent_leg.get("from_", "Unknown"),
            "agent_name": agent_name,
            "timestamp": agent_leg.get("start_time", ""),
            "direction": "outbound",
            "phone_from": agent_leg.get("from_", ""),
            "phone_to": "",
            "duration": agent_leg.get("duration", 0),
            "status": agent_leg.get("status", ""),
        }
    elif inbound_leg:
        # Inbound only (unanswered / IVR)
        return {
            "call_sid": inbound_leg["sid"],
            "agent_sid": "",
            "contact_name": inbound_leg.get("from_", "Unknown"),
            "agent_name": "",
            "timestamp": inbound_leg.get("start_time", ""),
            "direction": "inbound",
            "phone_from": inbound_leg.get("from_", ""),
            "phone_to": inbound_leg.get("to", ""),
            "duration": inbound_leg.get("duration", 0),
            "status": inbound_leg.get("status", ""),
        }
    else:
        return {
            "call_sid": "",
            "agent_sid": "",
            "contact_name": "Unknown",
            "agent_name": "",
            "timestamp": "",
            "direction": "unknown",
            "phone_from": "",
            "phone_to": "",
            "duration": 0,
            "status": "",
        }
