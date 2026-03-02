"""Tests for graph-enhanced FTS search expansion."""

from __future__ import annotations

from unittest.mock import MagicMock

from setkontext.ui.ranking import (
    _relationship_bonus,
    expand_entities_via_graph,
)


class TestExpandEntitiesViaGraph:
    def test_direct_entities_weight_1(self):
        repo = MagicMock()
        repo.get_related_entities.return_value = []
        result = expand_entities_via_graph(repo, {"fastapi", "redis"})
        assert result["fastapi"] == 1.0
        assert result["redis"] == 1.0

    def test_related_entities_weight_half(self):
        repo = MagicMock()
        repo.get_related_entities.side_effect = lambda e, depth=1: (
            [{"entity": "pydantic", "relationship": "uses", "confidence": "medium", "via": "fastapi"}]
            if e == "fastapi"
            else []
        )
        result = expand_entities_via_graph(repo, {"fastapi"})
        assert result["fastapi"] == 1.0
        assert result["pydantic"] == 0.5

    def test_empty_entities(self):
        repo = MagicMock()
        result = expand_entities_via_graph(repo, set())
        assert result == {}

    def test_direct_not_overwritten_by_related(self):
        """If an entity is both direct and related, keep weight 1.0."""
        repo = MagicMock()
        repo.get_related_entities.side_effect = lambda e, depth=1: (
            [{"entity": "redis", "relationship": "uses", "confidence": "medium", "via": "fastapi"}]
            if e == "fastapi"
            else []
        )
        result = expand_entities_via_graph(repo, {"fastapi", "redis"})
        assert result["redis"] == 1.0  # Not overwritten to 0.5


class TestRelationshipBonus:
    def test_bonus_for_related_entity(self):
        item = {"entities": [{"entity": "pydantic"}]}
        expanded = {"fastapi": 1.0, "pydantic": 0.5}
        bonus = _relationship_bonus(item, expanded)
        assert bonus > 0

    def test_no_bonus_for_direct_only(self):
        item = {"entities": [{"entity": "fastapi"}]}
        expanded = {"fastapi": 1.0}
        bonus = _relationship_bonus(item, expanded)
        assert bonus == 0.0

    def test_no_bonus_empty_entities(self):
        item = {"entities": []}
        expanded = {"fastapi": 1.0, "pydantic": 0.5}
        bonus = _relationship_bonus(item, expanded)
        assert bonus == 0.0

    def test_no_bonus_empty_expanded(self):
        item = {"entities": [{"entity": "fastapi"}]}
        bonus = _relationship_bonus(item, {})
        assert bonus == 0.0
