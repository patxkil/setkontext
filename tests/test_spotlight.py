"""Tests for Context Spotlight ranking logic."""

from __future__ import annotations

from setkontext.ui.page_spotlight import (
    _entity_overlap_score,
    _extract_entities_from_text,
    _relevance_indicator,
)


class TestExtractEntities:
    def test_finds_known_entities(self):
        known = {"redis", "postgresql", "fastapi"}
        result = _extract_entities_from_text("I need to add Redis caching", known)
        assert "redis" in result

    def test_case_insensitive(self):
        known = {"redis", "postgresql"}
        result = _extract_entities_from_text("Using REDIS for cache", known)
        assert "redis" in result

    def test_no_match(self):
        known = {"redis", "postgresql"}
        result = _extract_entities_from_text("Nothing related here", known)
        assert len(result) == 0


class TestEntityOverlapScore:
    def test_full_overlap(self):
        item = {"entities": [{"entity": "redis"}, {"entity": "postgresql"}]}
        score = _entity_overlap_score(item, {"redis", "postgresql"})
        assert score == 1.0

    def test_partial_overlap(self):
        item = {"entities": [{"entity": "redis"}]}
        score = _entity_overlap_score(item, {"redis", "postgresql"})
        assert score == 0.5

    def test_no_overlap(self):
        item = {"entities": [{"entity": "fastapi"}]}
        score = _entity_overlap_score(item, {"redis"})
        assert score == 0.0

    def test_empty_task_entities(self):
        item = {"entities": [{"entity": "redis"}]}
        score = _entity_overlap_score(item, set())
        assert score == 0.0

    def test_no_entities_on_item(self):
        item = {"entities": []}
        score = _entity_overlap_score(item, {"redis"})
        assert score == 0.0


class TestRelevanceIndicator:
    def test_high(self):
        assert "High" in _relevance_indicator(0.8)

    def test_medium(self):
        assert "Medium" in _relevance_indicator(0.5)

    def test_low(self):
        assert "Low" in _relevance_indicator(0.2)

    def test_boundary_high(self):
        assert "High" in _relevance_indicator(0.7)

    def test_boundary_medium(self):
        assert "Medium" in _relevance_indicator(0.4)
