"""Tests for naming module."""

import pytest

from src.naming import (
    build_filename,
    extract_first_name,
    format_contact,
    format_timestamp,
    slugify,
    _is_phone_number,
)


class TestSlugify:
    def test_basic(self):
        assert slugify("Sapochnick Law") == "sapochnick-law"

    def test_special_chars(self):
        assert slugify("JDC Mechanical!") == "jdc-mechanical"

    def test_max_length(self):
        result = slugify("Jacob Sapochnick Immigration Law Firm", max_length=20)
        assert len(result) <= 20
        assert result == "jacob-sapochnick"

    def test_empty(self):
        assert slugify("") == "unknown"
        assert slugify(None) == "unknown"

    def test_multiple_spaces(self):
        assert slugify("TTN   Law   Firm") == "ttn-law-firm"

    def test_already_slugified(self):
        assert slugify("ttn-law") == "ttn-law"

    def test_leading_trailing_special(self):
        assert slugify("--hello--") == "hello"

    def test_numbers(self):
        assert slugify("Route 66 Plumbing") == "route-66-plumbing"


class TestExtractFirstName:
    def test_full_name(self):
        assert extract_first_name("George Martinez") == "george"

    def test_single_name(self):
        assert extract_first_name("Sara") == "sara"

    def test_empty(self):
        assert extract_first_name("") == "unknown"
        assert extract_first_name(None) == "unknown"

    def test_whitespace(self):
        assert extract_first_name("  Burke  Campbell  ") == "burke"


class TestFormatTimestamp:
    def test_iso_utc(self):
        date, time = format_timestamp("2026-03-06T14:32:00Z")
        assert date == "2026-03-06"
        assert time == "1432"

    def test_iso_offset(self):
        date, time = format_timestamp("2026-03-06T14:32:00+00:00")
        assert date == "2026-03-06"
        assert time == "1432"

    def test_invalid(self):
        date, time = format_timestamp("not-a-date")
        assert date == "0000-00-00"
        assert time == "0000"

    def test_empty(self):
        date, time = format_timestamp("")
        assert date == "0000-00-00"
        assert time == "0000"

    def test_none(self):
        date, time = format_timestamp(None)
        assert date == "0000-00-00"
        assert time == "0000"


class TestIsPhoneNumber:
    def test_e164(self):
        assert _is_phone_number("+15551234567") is True

    def test_formatted(self):
        assert _is_phone_number("(555) 123-4567") is True

    def test_raw_digits(self):
        assert _is_phone_number("5551234567") is True

    def test_international(self):
        assert _is_phone_number("+923355499905") is True

    def test_name(self):
        assert _is_phone_number("Sapochnick Law") is False

    def test_empty(self):
        assert _is_phone_number("") is False

    def test_none(self):
        assert _is_phone_number(None) is False

    def test_short_digits(self):
        assert _is_phone_number("123") is False


class TestFormatContact:
    def test_phone_e164(self):
        assert format_contact("+15551234567") == "5551234567"

    def test_phone_international(self):
        assert format_contact("+923355499905") == "3355499905"

    def test_phone_formatted(self):
        assert format_contact("(403) 776-1148") == "4037761148"

    def test_business_name(self):
        assert format_contact("Sapochnick Law") == "sapochnick-law"

    def test_empty(self):
        assert format_contact("") == "unknown"

    def test_none(self):
        assert format_contact(None) == "unknown"


class TestBuildFilename:
    def test_full_record_with_name(self):
        record = {
            "contact_name": "Sapochnick Law",
            "agent_name": "George",
            "timestamp": "2026-03-06T14:32:00Z",
            "direction": "inbound",
            "recording_sid": "RE1234567890abcdef1234567890ab3f9a",
        }
        result = build_filename(record)
        assert result == "george_2026-03-06_1432_in_sapochnick-law_b3f9a.mp3"

    def test_full_record_with_phone(self):
        record = {
            "contact_name": "+14037761148",
            "agent_name": "George",
            "timestamp": "2026-03-06T20:05:00Z",
            "direction": "inbound",
            "recording_sid": "RE0000000000000000000000000af89c",
        }
        result = build_filename(record)
        assert result == "george_2026-03-06_2005_in_4037761148_af89c.mp3"

    def test_no_agent(self):
        record = {
            "contact_name": "TTN Law",
            "agent_name": "",
            "timestamp": "2026-03-05T09:12:00Z",
            "direction": "inbound",
            "call_sid": "CA1234567890abcdefghijklmnopqb2e1",
        }
        result = build_filename(record)
        assert result == "noagent_2026-03-05_0912_in_ttn-law_qb2e1.mp3"

    def test_outbound(self):
        record = {
            "contact_name": "Moe's Services",
            "agent_name": "Daniel",
            "timestamp": "2026-03-07T16:01:00Z",
            "direction": "outbound",
            "recording_sid": "RExxxxxxxxxxxxxxxxxxxxxxxxxx77d3",
        }
        result = build_filename(record)
        assert result == "daniel_2026-03-07_1601_out_moes-services_x77d3.mp3"

    def test_empty_record(self):
        result = build_filename({})
        assert result == "noagent_0000-00-00_0000_unk_unknown_00000.mp3"

    def test_special_chars_in_name(self):
        record = {
            "contact_name": "O'Brien & Associates (LLC)",
            "agent_name": "Sara",
            "timestamp": "2026-01-15T08:00:00Z",
            "direction": "inbound",
            "recording_sid": "RE0000000000000000000000000abc12",
        }
        result = build_filename(record)
        assert result.startswith("sara_")
        assert "_in_" in result
        assert "obrien" in result
        assert result.endswith(".mp3")

    def test_direction_abbreviation(self):
        record = {
            "contact_name": "Test",
            "agent_name": "Agent",
            "timestamp": "2026-01-01T00:00:00Z",
            "direction": "inbound",
            "call_sid": "CA00000",
        }
        assert "_in_" in build_filename(record)
        record["direction"] = "outbound"
        assert "_out_" in build_filename(record)
        record["direction"] = "internal"
        assert "_unk_" in build_filename(record)

    def test_agent_first_name_only(self):
        record = {
            "contact_name": "Test Client",
            "agent_name": "George Martinez",
            "timestamp": "2026-03-06T14:32:00Z",
            "direction": "inbound",
            "call_sid": "CA12345",
        }
        result = build_filename(record)
        assert result.startswith("george_")
        assert "martinez" not in result

    def test_sorts_chronologically(self):
        """Files for same agent on same day sort by time."""
        base = {
            "contact_name": "+15551234567",
            "agent_name": "george",
            "direction": "inbound",
            "call_sid": "CA00000",
        }
        f1 = build_filename({**base, "timestamp": "2026-03-06T20:05:00Z"})
        f2 = build_filename({**base, "timestamp": "2026-03-06T20:33:00Z"})
        f3 = build_filename({**base, "timestamp": "2026-03-06T22:21:00Z"})
        assert f1 < f2 < f3
