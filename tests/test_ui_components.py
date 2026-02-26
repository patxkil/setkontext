"""Tests for UI component utilities (pure logic, no Streamlit rendering)."""

from __future__ import annotations

from setkontext.ui.components import build_fts_query, category_badge, confidence_badge


class TestConfidenceBadge:
    def test_high(self):
        assert "\U0001f7e2" in confidence_badge("high")

    def test_medium(self):
        assert "\U0001f7e1" in confidence_badge("medium")

    def test_low(self):
        assert "\U0001f534" in confidence_badge("low")

    def test_unknown(self):
        assert "\u26aa" in confidence_badge("unknown")


class TestCategoryBadge:
    def test_bug_fix(self):
        badge = category_badge("bug_fix")
        assert "BUG FIX" in badge

    def test_gotcha(self):
        badge = category_badge("gotcha")
        assert "GOTCHA" in badge

    def test_implementation(self):
        badge = category_badge("implementation")
        assert "IMPLEMENTATION" in badge

    def test_unknown(self):
        badge = category_badge("unknown_cat")
        assert "UNKNOWN_CAT" in badge


class TestBuildFtsQuery:
    def test_strips_stop_words(self):
        query = build_fts_query("why did we choose PostgreSQL?")
        assert "why" not in query.lower().split(" or ")
        assert "postgresql" in query.lower()

    def test_strips_short_words(self):
        query = build_fts_query("is it ok to use Go?")
        # "go" is 2 chars, should be stripped
        terms = [t.strip() for t in query.lower().split(" or ")]
        assert "go" not in terms

    def test_joins_with_or(self):
        query = build_fts_query("PostgreSQL migration strategy")
        assert " OR " in query

    def test_empty_input(self):
        assert build_fts_query("") == ""

    def test_all_stop_words(self):
        assert build_fts_query("why did we do this?") == ""

    def test_strips_punctuation(self):
        query = build_fts_query("redis? caching!")
        assert "redis" in query.lower()
        assert "caching" in query.lower()
        assert "?" not in query
        assert "!" not in query
