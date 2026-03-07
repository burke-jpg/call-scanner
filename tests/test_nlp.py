"""Tests for natural language query parser."""

import os
from datetime import date

import pytest

from src.nlp import (
    ParsedQuery,
    get_known_agents,
    parse_query,
    _most_recent_weekday,
    _previous_week_weekday,
)


# Fixed reference date: Saturday March 7, 2026
REF = date(2026, 3, 7)


# ------------------------------------------------------------------ #
#  Agent matching                                                      #
# ------------------------------------------------------------------ #

class TestAgentParsing:
    def test_single_agent(self):
        q = parse_query("george", REF)
        assert q.agent == "george"

    def test_agent_case_insensitive(self):
        q = parse_query("SARA", REF)
        assert q.agent == "sara"

    def test_agent_with_date(self):
        q = parse_query("george tuesday", REF)
        assert q.agent == "george"
        assert q.date == "2026-03-03"

    def test_agent_with_time(self):
        q = parse_query("omar morning", REF)
        assert q.agent == "omar"
        assert q.time_from == "06:00"
        assert q.time_to == "12:00"

    def test_unknown_agent_becomes_client(self):
        q = parse_query("jennifer", REF)
        assert q.agent is None
        assert q.client == "jennifer"

    def test_burke_is_recognized(self):
        q = parse_query("burke yesterday", REF)
        assert q.agent == "burke"
        assert q.date == "2026-03-06"


# ------------------------------------------------------------------ #
#  Relative dates                                                      #
# ------------------------------------------------------------------ #

class TestDateParsing:
    def test_today(self):
        q = parse_query("today", REF)
        assert q.date == "2026-03-07"

    def test_yesterday(self):
        q = parse_query("yesterday", REF)
        assert q.date == "2026-03-06"

    def test_weekday_tuesday(self):
        # REF is Saturday 3/7, most recent Tuesday = 3/3
        q = parse_query("tuesday", REF)
        assert q.date == "2026-03-03"

    def test_weekday_friday(self):
        # REF is Saturday 3/7, most recent Friday = 3/6
        q = parse_query("friday", REF)
        assert q.date == "2026-03-06"

    def test_weekday_saturday_is_today(self):
        # REF is Saturday 3/7, most recent Saturday = today
        q = parse_query("saturday", REF)
        assert q.date == "2026-03-07"

    def test_weekday_abbreviation(self):
        q = parse_query("tue", REF)
        assert q.date == "2026-03-03"

    def test_this_week(self):
        # Monday 3/2 through Saturday 3/7
        q = parse_query("this week", REF)
        assert q.date_from == "2026-03-02"
        assert q.date_to == "2026-03-07"

    def test_last_week(self):
        # Previous Monday 2/23 through Sunday 3/1
        q = parse_query("last week", REF)
        assert q.date_from == "2026-02-23"
        assert q.date_to == "2026-03-01"

    def test_last_tuesday(self):
        # "last tuesday" = previous week's Tuesday = 2/24
        q = parse_query("last tuesday", REF)
        assert q.date == "2026-02-24"

    def test_last_saturday(self):
        # "last saturday" when today IS Saturday → previous Saturday = 2/28
        q = parse_query("last saturday", REF)
        assert q.date == "2026-02-28"

    def test_iso_date(self):
        q = parse_query("2026-03-05", REF)
        assert q.date == "2026-03-05"


# ------------------------------------------------------------------ #
#  Time of day                                                         #
# ------------------------------------------------------------------ #

class TestTimeParsing:
    def test_morning(self):
        q = parse_query("morning", REF)
        assert q.time_from == "06:00"
        assert q.time_to == "12:00"

    def test_afternoon(self):
        q = parse_query("afternoon", REF)
        assert q.time_from == "12:00"
        assert q.time_to == "17:00"

    def test_evening(self):
        q = parse_query("evening", REF)
        assert q.time_from == "17:00"
        assert q.time_to == "22:00"

    def test_night(self):
        q = parse_query("night", REF)
        assert q.time_from == "17:00"
        assert q.time_to == "23:59"


# ------------------------------------------------------------------ #
#  Direction                                                           #
# ------------------------------------------------------------------ #

class TestDirectionParsing:
    def test_inbound(self):
        q = parse_query("inbound", REF)
        assert q.direction == "inbound"

    def test_outbound(self):
        q = parse_query("outbound", REF)
        assert q.direction == "outbound"

    def test_direction_with_agent(self):
        q = parse_query("george inbound", REF)
        assert q.direction == "inbound"
        assert q.agent == "george"


# ------------------------------------------------------------------ #
#  Limits                                                              #
# ------------------------------------------------------------------ #

class TestLimitParsing:
    def test_last_5(self):
        q = parse_query("last 5", REF)
        assert q.limit == 5
        assert q.limit_from == "tail"

    def test_first_3(self):
        q = parse_query("first 3", REF)
        assert q.limit == 3
        assert q.limit_from == "head"

    def test_latest_10(self):
        q = parse_query("latest 10", REF)
        assert q.limit == 10
        assert q.limit_from == "tail"

    def test_recent_2(self):
        q = parse_query("recent 2", REF)
        assert q.limit == 2
        assert q.limit_from == "tail"

    def test_last_not_followed_by_number(self):
        # "last week" should parse as date range, not limit
        q = parse_query("last week", REF)
        assert q.limit is None
        assert q.date_from is not None


# ------------------------------------------------------------------ #
#  Client / remainder                                                  #
# ------------------------------------------------------------------ #

class TestClientParsing:
    def test_client_name(self):
        q = parse_query("sapochnick", REF)
        assert q.client == "sapochnick"

    def test_client_multi_word(self):
        q = parse_query("ttn law", REF)
        assert q.client == "ttn law"

    def test_stopwords_removed(self):
        q = parse_query("calls with sapochnick", REF)
        assert q.client == "sapochnick"

    def test_agent_not_in_client(self):
        q = parse_query("george sapochnick", REF)
        assert q.agent == "george"
        assert q.client == "sapochnick"


# ------------------------------------------------------------------ #
#  Phone numbers                                                       #
# ------------------------------------------------------------------ #

class TestPhoneParsing:
    def test_phone_number(self):
        q = parse_query("+14037761148", REF)
        assert q.phone == "+14037761148"

    def test_phone_digits_only(self):
        q = parse_query("4037761148", REF)
        assert q.phone == "4037761148"


# ------------------------------------------------------------------ #
#  Integration queries                                                 #
# ------------------------------------------------------------------ #

class TestIntegrationQueries:
    def test_george_tuesday_morning(self):
        q = parse_query("George Tuesday morning", REF)
        assert q.agent == "george"
        assert q.date == "2026-03-03"
        assert q.time_from == "06:00"
        assert q.time_to == "12:00"

    def test_sara_yesterday(self):
        q = parse_query("Sara yesterday", REF)
        assert q.agent == "sara"
        assert q.date == "2026-03-06"

    def test_last_5_calls(self):
        q = parse_query("last 5 calls", REF)
        assert q.limit == 5
        assert q.limit_from == "tail"

    def test_calls_with_sapochnick(self):
        q = parse_query("calls with Sapochnick", REF)
        assert q.client == "sapochnick"

    def test_george_this_week(self):
        q = parse_query("george this week", REF)
        assert q.agent == "george"
        assert q.date_from == "2026-03-02"
        assert q.date_to == "2026-03-07"

    def test_inbound_danny_friday_afternoon(self):
        q = parse_query("inbound danny friday afternoon", REF)
        assert q.direction == "inbound"
        assert q.agent == "danny"
        assert q.date == "2026-03-06"
        assert q.time_from == "12:00"
        assert q.time_to == "17:00"

    def test_outbound_last_3(self):
        q = parse_query("outbound last 3", REF)
        assert q.direction == "outbound"
        assert q.limit == 3

    def test_full_complex_query(self):
        q = parse_query("show me george inbound tuesday morning sapochnick", REF)
        assert q.agent == "george"
        assert q.direction == "inbound"
        assert q.date == "2026-03-03"
        assert q.time_from == "06:00"
        assert q.client == "sapochnick"


# ------------------------------------------------------------------ #
#  Edge cases                                                          #
# ------------------------------------------------------------------ #

class TestEdgeCases:
    def test_empty_string(self):
        q = parse_query("", REF)
        assert not q.has_filters()

    def test_none(self):
        q = parse_query(None, REF)
        assert not q.has_filters()

    def test_whitespace_only(self):
        q = parse_query("   ", REF)
        assert not q.has_filters()

    def test_all_stopwords(self):
        q = parse_query("show me all the calls", REF)
        assert not q.has_filters()

    def test_summary_method(self):
        q = parse_query("george tuesday morning", REF)
        s = q.summary()
        assert "agent=george" in s
        assert "date=2026-03-03" in s
        assert "time=06:00-12:00" in s


# ------------------------------------------------------------------ #
#  Agent list configuration                                            #
# ------------------------------------------------------------------ #

class TestAgentConfig:
    def test_default_agents(self):
        agents = get_known_agents()
        assert "george" in agents
        assert "sara" in agents
        assert "danny" in agents
        assert "burke" in agents

    def test_custom_agents_env(self, monkeypatch):
        monkeypatch.setenv("KNOWN_AGENTS", "alice,bob,charlie")
        agents = get_known_agents()
        assert agents == ["alice", "bob", "charlie"]

    def test_custom_agent_recognized(self, monkeypatch):
        monkeypatch.setenv("KNOWN_AGENTS", "alice,bob")
        q = parse_query("alice today", REF)
        assert q.agent == "alice"


# ------------------------------------------------------------------ #
#  Helper functions                                                    #
# ------------------------------------------------------------------ #

class TestHelpers:
    def test_most_recent_weekday_today(self):
        # Saturday is weekday 5, ref is Saturday
        assert _most_recent_weekday(5, REF) == REF

    def test_most_recent_weekday_past(self):
        # Tuesday is weekday 1, most recent from Saturday = 3/3
        assert _most_recent_weekday(1, REF) == date(2026, 3, 3)

    def test_previous_week_weekday_same_day(self):
        # "last saturday" from Saturday → previous Saturday
        assert _previous_week_weekday(5, REF) == date(2026, 2, 28)

    def test_previous_week_weekday_different(self):
        # "last tuesday" from Saturday → 2/24 (not 3/3)
        assert _previous_week_weekday(1, REF) == date(2026, 2, 24)
