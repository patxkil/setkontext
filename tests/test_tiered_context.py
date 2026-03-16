"""Tests for tiered context responses (L0/L1/L2)."""

from __future__ import annotations

from setkontext.mcp_server import (
    L1_MAX_CHARS,
    _shape_decision,
    _shape_items,
    _shape_learning,
)


def _make_decision(**overrides) -> dict:
    defaults = {
        "id": "dec-001",
        "summary": "Use PostgreSQL for primary datastore",
        "reasoning": "Long reasoning text. " * 100,  # ~2000 chars
        "alternatives": ["MySQL", "SQLite"],
        "confidence": "high",
        "decision_date": "2024-06-15",
        "entities": [{"entity": "postgresql", "entity_type": "technology"}],
        "source_url": "https://github.com/acme/app/pull/42",
        "source_title": "Migrate to PostgreSQL",
        "source_type": "pr",
        "extracted_at": "2024-06-15T12:00:00",
        "source_id": "pr:42",
    }
    defaults.update(overrides)
    return defaults


def _make_learning(**overrides) -> dict:
    defaults = {
        "id": "learn-001",
        "summary": "Fixed session timeout caused by incorrect TTL",
        "category": "bug_fix",
        "detail": "Detailed explanation of the bug. " * 100,  # ~3500 chars
        "components": ["auth/session.py"],
        "session_date": "2024-08-10",
        "entities": [{"entity": "redis", "entity_type": "technology"}],
        "source_url": "",
        "source_title": "[claude-code] Fix auth",
        "source_type": "learning",
        "extracted_at": "2024-08-10T14:00:00",
        "source_id": "learning:session-abc",
    }
    defaults.update(overrides)
    return defaults


class TestShapeDecision:
    def test_summary_returns_minimal_fields(self):
        d = _make_decision()
        shaped = _shape_decision(d, "summary")
        assert "summary" in shaped
        assert "confidence" in shaped
        assert "entities" in shaped
        assert "reasoning" not in shaped
        assert "alternatives" not in shaped
        assert "source_id" not in shaped

    def test_standard_truncates_long_reasoning(self):
        d = _make_decision()
        assert len(d["reasoning"]) > L1_MAX_CHARS
        shaped = _shape_decision(d, "standard")
        assert shaped["reasoning"].endswith("...")
        assert len(shaped["reasoning"]) <= L1_MAX_CHARS + 3  # +3 for "..."

    def test_standard_keeps_short_reasoning(self):
        d = _make_decision(reasoning="Short reason.")
        shaped = _shape_decision(d, "standard")
        assert shaped["reasoning"] == "Short reason."

    def test_full_returns_everything(self):
        d = _make_decision()
        shaped = _shape_decision(d, "full")
        assert shaped == d
        assert len(shaped["reasoning"]) > L1_MAX_CHARS


class TestShapeLearning:
    def test_summary_returns_minimal_fields(self):
        l = _make_learning()
        shaped = _shape_learning(l, "summary")
        assert "summary" in shaped
        assert "category" in shaped
        assert "entities" in shaped
        assert "detail" not in shaped
        assert "source_id" not in shaped

    def test_standard_truncates_long_detail(self):
        l = _make_learning()
        assert len(l["detail"]) > L1_MAX_CHARS
        shaped = _shape_learning(l, "standard")
        assert shaped["detail"].endswith("...")
        assert len(shaped["detail"]) <= L1_MAX_CHARS + 3

    def test_standard_keeps_short_detail(self):
        l = _make_learning(detail="Short detail.")
        shaped = _shape_learning(l, "standard")
        assert shaped["detail"] == "Short detail."

    def test_full_returns_everything(self):
        l = _make_learning()
        shaped = _shape_learning(l, "full")
        assert shaped == l


class TestShapeItems:
    def test_shapes_mixed_list(self):
        items = [
            {**_make_decision(), "_type": "decision"},
            {**_make_learning(), "_type": "learning"},
        ]
        shaped = _shape_items(items, "summary")
        assert len(shaped) == 2
        assert "reasoning" not in shaped[0]
        assert "detail" not in shaped[1]

    def test_detects_learning_by_category(self):
        """Learnings without _type should be detected by 'category' field."""
        l = _make_learning()  # no _type field
        shaped = _shape_items([l], "summary")
        assert "detail" not in shaped[0]
        assert "category" in shaped[0]

    def test_empty_list(self):
        assert _shape_items([], "standard") == []


class TestTokenSavings:
    """Verify the tiered approach actually saves tokens."""

    def test_summary_much_smaller_than_full(self):
        d = _make_decision()
        summary = _shape_decision(d, "summary")
        full = _shape_decision(d, "full")
        summary_size = len(str(summary))
        full_size = len(str(full))
        # Summary should be at least 3x smaller
        assert summary_size < full_size / 3

    def test_standard_smaller_than_full(self):
        d = _make_decision()
        standard = _shape_decision(d, "standard")
        full = _shape_decision(d, "full")
        standard_size = len(str(standard))
        full_size = len(str(full))
        assert standard_size < full_size
