"""Tests for UI component utilities (pure logic, no Streamlit rendering)."""

from __future__ import annotations

from setkontext.ui.components import build_fts_query, category_badge, confidence_badge


class TestConfidenceBadge:
    def test_high(self):
        badge = confidence_badge("high")
        assert "sk-badge-high" in badge
        assert "HIGH" in badge

    def test_medium(self):
        badge = confidence_badge("medium")
        assert "sk-badge-medium" in badge
        assert "MEDIUM" in badge

    def test_low(self):
        badge = confidence_badge("low")
        assert "sk-badge-low" in badge
        assert "LOW" in badge

    def test_unknown(self):
        badge = confidence_badge("unknown")
        assert "sk-badge-low" in badge
        assert "UNKNOWN" in badge


class TestCategoryBadge:
    def test_bug_fix(self):
        badge = category_badge("bug_fix")
        assert "sk-badge-bug-fix" in badge
        assert "Bug Fix" in badge

    def test_gotcha(self):
        badge = category_badge("gotcha")
        assert "sk-badge-gotcha" in badge
        assert "Gotcha" in badge

    def test_implementation(self):
        badge = category_badge("implementation")
        assert "sk-badge-implementation" in badge
        assert "Implementation" in badge

    def test_unknown(self):
        badge = category_badge("unknown_cat")
        assert "sk-badge-implementation" in badge
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
