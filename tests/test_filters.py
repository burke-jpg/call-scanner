"""Tests for filters module."""

import pytest

from src.filters import (
    apply_filters,
    matches_agent,
    matches_client,
    matches_date_range,
    matches_phone,
    matches_time_range,
)


SAMPLE_RECORDS = [
    {
        "call_sid": "CA001",
        "contact_name": "Sapochnick Law",
        "agent_name": "George",
        "timestamp": "2026-03-06T14:32:00Z",
        "direction": "inbound",
        "phone_from": "+15551234567",
        "phone_to": "+18005559999",
    },
    {
        "call_sid": "CA002",
        "contact_name": "TTN Law",
        "agent_name": "Sara",
        "timestamp": "2026-03-06T09:15:00Z",
        "direction": "inbound",
        "phone_from": "+15559876543",
        "phone_to": "+18005559999",
    },
    {
        "call_sid": "CA003",
        "contact_name": "JDC Mechanical",
        "agent_name": "Omar",
        "timestamp": "2026-03-07T16:45:00Z",
        "direction": "outbound",
        "phone_from": "+18005559999",
        "phone_to": "+15551112222",
    },
    {
        "call_sid": "CA004",
        "contact_name": "Moe's Services",
        "agent_name": "George",
        "timestamp": "2026-03-05T11:00:00Z",
        "direction": "inbound",
        "phone_from": "+15553334444",
        "phone_to": "+18005559999",
    },
]


class TestMatchesDateRange:
    def test_single_date_match(self):
        assert matches_date_range("2026-03-06T14:32:00Z", date="2026-03-06")

    def test_single_date_no_match(self):
        assert not matches_date_range("2026-03-07T14:32:00Z", date="2026-03-06")

    def test_date_range(self):
        assert matches_date_range(
            "2026-03-06T14:32:00Z", date_from="2026-03-05", date_to="2026-03-07"
        )

    def test_date_range_boundary(self):
        assert matches_date_range(
            "2026-03-05T00:00:00Z", date_from="2026-03-05", date_to="2026-03-07"
        )
        assert matches_date_range(
            "2026-03-07T23:59:59Z", date_from="2026-03-05", date_to="2026-03-07"
        )

    def test_date_range_outside(self):
        assert not matches_date_range(
            "2026-03-04T23:59:59Z", date_from="2026-03-05", date_to="2026-03-07"
        )

    def test_no_filter(self):
        assert matches_date_range("2026-03-06T14:32:00Z")

    def test_invalid_timestamp(self):
        assert not matches_date_range("invalid", date="2026-03-06")


class TestMatchesTimeRange:
    def test_within_range(self):
        assert matches_time_range(
            "2026-03-06T14:32:00Z", time_from="14:00", time_to="17:00"
        )

    def test_before_range(self):
        assert not matches_time_range(
            "2026-03-06T09:15:00Z", time_from="14:00", time_to="17:00"
        )

    def test_after_range(self):
        assert not matches_time_range(
            "2026-03-06T18:00:00Z", time_from="14:00", time_to="17:00"
        )

    def test_no_filter(self):
        assert matches_time_range("2026-03-06T14:32:00Z")

    def test_only_from(self):
        assert matches_time_range("2026-03-06T14:32:00Z", time_from="14:00")
        assert not matches_time_range("2026-03-06T09:00:00Z", time_from="14:00")

    def test_only_to(self):
        assert matches_time_range("2026-03-06T14:32:00Z", time_to="17:00")
        assert not matches_time_range("2026-03-06T18:00:00Z", time_to="17:00")


class TestMatchesAgent:
    def test_exact(self):
        assert matches_agent({"agent_name": "George"}, "George")

    def test_partial(self):
        assert matches_agent({"agent_name": "George Martinez"}, "george")

    def test_case_insensitive(self):
        assert matches_agent({"agent_name": "Sara"}, "SARA")

    def test_no_match(self):
        assert not matches_agent({"agent_name": "Sara"}, "George")

    def test_no_filter(self):
        assert matches_agent({"agent_name": "Sara"}, None)

    def test_empty_agent(self):
        assert not matches_agent({"agent_name": ""}, "George")


class TestMatchesClient:
    def test_partial(self):
        assert matches_client({"contact_name": "Sapochnick Law"}, "sapochnick")

    def test_case_insensitive(self):
        assert matches_client({"contact_name": "TTN Law"}, "ttn")

    def test_no_match(self):
        assert not matches_client({"contact_name": "TTN Law"}, "sapochnick")

    def test_no_filter(self):
        assert matches_client({"contact_name": "TTN Law"}, None)


class TestMatchesPhone:
    def test_from_match(self):
        assert matches_phone(
            {"phone_from": "+15551234567", "phone_to": "+18005559999"},
            "5551234567",
        )

    def test_to_match(self):
        assert matches_phone(
            {"phone_from": "+15551234567", "phone_to": "+18005559999"},
            "8005559999",
        )

    def test_partial(self):
        assert matches_phone(
            {"phone_from": "+15551234567", "phone_to": ""},
            "1234567",
        )

    def test_no_match(self):
        assert not matches_phone(
            {"phone_from": "+15551234567", "phone_to": "+18005559999"},
            "9999999999",
        )

    def test_no_filter(self):
        assert matches_phone({"phone_from": "+15551234567", "phone_to": ""}, None)


class TestApplyFilters:
    def test_filter_by_date(self):
        result = apply_filters(SAMPLE_RECORDS, date="2026-03-06")
        assert len(result) == 2
        assert all(r["call_sid"] in ("CA001", "CA002") for r in result)

    def test_filter_by_agent(self):
        result = apply_filters(SAMPLE_RECORDS, agent="george")
        assert len(result) == 2
        assert all(r["agent_name"] == "George" for r in result)

    def test_filter_by_client(self):
        result = apply_filters(SAMPLE_RECORDS, client="sapochnick")
        assert len(result) == 1
        assert result[0]["call_sid"] == "CA001"

    def test_filter_by_date_and_time(self):
        result = apply_filters(
            SAMPLE_RECORDS,
            date="2026-03-06",
            time_from="14:00",
            time_to="17:00",
        )
        assert len(result) == 1
        assert result[0]["call_sid"] == "CA001"

    def test_filter_by_date_range(self):
        result = apply_filters(
            SAMPLE_RECORDS, date_from="2026-03-05", date_to="2026-03-06"
        )
        assert len(result) == 3

    def test_combined_filters(self):
        result = apply_filters(
            SAMPLE_RECORDS, date="2026-03-06", agent="george"
        )
        assert len(result) == 1
        assert result[0]["call_sid"] == "CA001"

    def test_no_filters_returns_all(self):
        result = apply_filters(SAMPLE_RECORDS)
        assert len(result) == 4

    def test_no_matches(self):
        result = apply_filters(SAMPLE_RECORDS, client="nonexistent")
        assert len(result) == 0

    def test_phone_filter(self):
        result = apply_filters(SAMPLE_RECORDS, phone="5551234567")
        assert len(result) == 1
        assert result[0]["call_sid"] == "CA001"
