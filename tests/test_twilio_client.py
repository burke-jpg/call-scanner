"""Tests for Twilio client module (Twilio-first architecture).

Tests for pure functions: extract_agent, normalize_phone, parse_iso, _build_record.
TwilioClient methods that hit the API are not tested here (integration tests).
"""

import pytest
from datetime import datetime, timezone

from src.twilio_client import (
    extract_agent,
    normalize_phone,
    parse_iso,
    _build_record,
)


# ------------------------------------------------------------------ #
#  extract_agent                                                       #
# ------------------------------------------------------------------ #

class TestExtractAgent:
    def test_full_email_encoded(self):
        assert extract_agent("client:george_40jumpcontact_2Ecom") == "george"

    def test_simple_name(self):
        assert extract_agent("client:anthony") == "anthony"

    def test_case_insensitive_prefix(self):
        assert extract_agent("Client:sara_40jumpcontact_2Ecom") == "sara"

    def test_multiple_hex_codes(self):
        # _40 = @, _2E = .
        assert extract_agent("client:omar_40jump_2Econtact_2Ecom") == "omar"

    def test_not_client_uri(self):
        assert extract_agent("+15551234567") == ""

    def test_sip_uri(self):
        assert extract_agent("sip:agent@domain.com") == ""

    def test_empty_string(self):
        assert extract_agent("") == ""

    def test_none(self):
        assert extract_agent(None) == ""

    def test_client_prefix_only(self):
        assert extract_agent("client:") == ""

    def test_name_with_dots(self):
        # george.martinez@jumpcontact.com
        assert extract_agent("client:george_2Emartinez_40jumpcontact_2Ecom") == "george.martinez"

    def test_uppercase_hex(self):
        assert extract_agent("client:danny_40jumpcontact_2Ecom") == "danny"

    def test_preserves_lowercase(self):
        assert extract_agent("client:BURKE_40jumpcontact_2Ecom") == "burke"


# ------------------------------------------------------------------ #
#  normalize_phone                                                     #
# ------------------------------------------------------------------ #

class TestNormalizePhone:
    def test_with_plus(self):
        assert normalize_phone("+15551234567") == "15551234567"

    def test_with_dashes(self):
        assert normalize_phone("555-123-4567") == "5551234567"

    def test_with_spaces(self):
        assert normalize_phone("+1 555 123 4567") == "15551234567"

    def test_with_parens(self):
        assert normalize_phone("(555) 123-4567") == "5551234567"

    def test_already_clean(self):
        assert normalize_phone("5551234567") == "5551234567"

    def test_empty(self):
        assert normalize_phone("") == ""

    def test_none(self):
        assert normalize_phone(None) == ""


# ------------------------------------------------------------------ #
#  parse_iso                                                           #
# ------------------------------------------------------------------ #

class TestParseIso:
    def test_utc_z(self):
        result = parse_iso("2026-03-06T14:32:00Z")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 32

    def test_utc_offset(self):
        result = parse_iso("2026-03-06T14:32:00+00:00")
        assert result is not None
        assert result.hour == 14

    def test_negative_offset(self):
        result = parse_iso("2026-03-06T14:32:00-05:00")
        assert result is not None

    def test_empty(self):
        assert parse_iso("") is None

    def test_none(self):
        assert parse_iso(None) is None

    def test_invalid(self):
        assert parse_iso("not-a-date") is None

    def test_partial(self):
        assert parse_iso("2026-03-06") is not None  # date-only is valid ISO


# ------------------------------------------------------------------ #
#  _build_record                                                       #
# ------------------------------------------------------------------ #

INBOUND_LEG = {
    "sid": "CA_INBOUND_001",
    "from_": "+15551234567",
    "to": "+18005559999",
    "direction": "inbound",
    "start_time": "2026-03-06T14:32:00Z",
    "duration": 120,
    "status": "completed",
}

AGENT_LEG = {
    "sid": "CA_AGENT_001",
    "from_": "+18005559999",
    "to": "client:george_40jumpcontact_2Ecom",
    "direction": "outbound-api",
    "start_time": "2026-03-06T14:32:05Z",
    "duration": 115,
    "status": "completed",
}


class TestBuildRecord:
    def test_paired_call(self):
        record = _build_record(AGENT_LEG, INBOUND_LEG, "george")
        assert record["call_sid"] == "CA_INBOUND_001"
        assert record["agent_sid"] == "CA_AGENT_001"
        assert record["agent_name"] == "george"
        assert record["direction"] == "inbound"
        assert record["phone_from"] == "+15551234567"
        assert record["phone_to"] == "+18005559999"
        assert record["duration"] == 120  # max of both legs

    def test_paired_uses_max_duration(self):
        long_agent = {**AGENT_LEG, "duration": 200}
        record = _build_record(long_agent, INBOUND_LEG, "george")
        assert record["duration"] == 200

    def test_agent_only(self):
        record = _build_record(AGENT_LEG, None, "george")
        assert record["call_sid"] == "CA_AGENT_001"
        assert record["agent_sid"] == "CA_AGENT_001"
        assert record["agent_name"] == "george"
        assert record["direction"] == "outbound"

    def test_inbound_only(self):
        record = _build_record(None, INBOUND_LEG, "")
        assert record["call_sid"] == "CA_INBOUND_001"
        assert record["agent_sid"] == ""
        assert record["agent_name"] == ""
        assert record["direction"] == "inbound"
        assert record["phone_from"] == "+15551234567"

    def test_both_none(self):
        record = _build_record(None, None, "")
        assert record["call_sid"] == ""
        assert record["agent_sid"] == ""
        assert record["contact_name"] == "Unknown"
        assert record["direction"] == "unknown"
        assert record["duration"] == 0

    def test_paired_contact_name_from_inbound(self):
        record = _build_record(AGENT_LEG, INBOUND_LEG, "george")
        assert record["contact_name"] == "+15551234567"

    def test_agent_only_contact_from_agent(self):
        record = _build_record(AGENT_LEG, None, "george")
        assert record["contact_name"] == "+18005559999"


# ------------------------------------------------------------------ #
#  pair_call_legs (unit test with mock data, no API)                    #
# ------------------------------------------------------------------ #

class TestPairCallLegsLogic:
    """Test pairing logic by calling pair_call_legs with synthetic data.

    We can't call TwilioClient.pair_call_legs without instantiation,
    so we test the pairing pattern with _build_record directly.
    """

    def test_paired_record_has_both_sids(self):
        record = _build_record(AGENT_LEG, INBOUND_LEG, "george")
        assert record["call_sid"] != record["agent_sid"]
        assert record["call_sid"] == INBOUND_LEG["sid"]
        assert record["agent_sid"] == AGENT_LEG["sid"]

    def test_unmatched_agent_has_same_sid(self):
        record = _build_record(AGENT_LEG, None, "george")
        assert record["call_sid"] == record["agent_sid"]

    def test_unmatched_inbound_has_no_agent_sid(self):
        record = _build_record(None, INBOUND_LEG, "")
        assert record["agent_sid"] == ""
        assert record["call_sid"] == INBOUND_LEG["sid"]

    def test_timestamp_from_inbound_when_paired(self):
        record = _build_record(AGENT_LEG, INBOUND_LEG, "george")
        assert record["timestamp"] == INBOUND_LEG["start_time"]

    def test_timestamp_from_agent_when_alone(self):
        record = _build_record(AGENT_LEG, None, "george")
        assert record["timestamp"] == AGENT_LEG["start_time"]
