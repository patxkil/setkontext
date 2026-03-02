"""Tests for entity graph DOT visualization."""

from __future__ import annotations

from setkontext.ui.graph import build_entity_dot_graph


class TestBuildEntityDotGraph:
    def test_empty_graph(self):
        result = build_entity_dot_graph({"nodes": [], "edges": []})
        assert "No entities found" in result

    def test_basic_graph(self):
        graph_data = {
            "nodes": [
                {"entity": "fastapi", "entity_type": "technology", "decision_count": 2, "learning_count": 1},
                {"entity": "pydantic", "entity_type": "library", "decision_count": 1, "learning_count": 0},
            ],
            "edges": [
                {"from_entity": "fastapi", "to_entity": "pydantic", "relationship": "uses", "confidence": "high"},
            ],
        }
        dot = build_entity_dot_graph(graph_data)
        assert "digraph" in dot
        assert "fastapi" in dot
        assert "pydantic" in dot
        assert "uses" in dot

    def test_highlight_entity(self):
        graph_data = {
            "nodes": [
                {"entity": "fastapi", "entity_type": "technology", "decision_count": 2, "learning_count": 0},
                {"entity": "pydantic", "entity_type": "library", "decision_count": 1, "learning_count": 0},
                {"entity": "redis", "entity_type": "technology", "decision_count": 1, "learning_count": 0},
            ],
            "edges": [
                {"from_entity": "fastapi", "to_entity": "pydantic", "relationship": "uses", "confidence": "high"},
            ],
        }
        # Highlighting fastapi should include pydantic (neighbor) but not redis (unconnected)
        dot = build_entity_dot_graph(graph_data, highlight="fastapi")
        assert "fastapi" in dot
        assert "pydantic" in dot
        assert "redis" not in dot

    def test_relationship_styles(self):
        graph_data = {
            "nodes": [
                {"entity": "postgresql", "entity_type": "technology", "decision_count": 1, "learning_count": 0},
                {"entity": "mongodb", "entity_type": "technology", "decision_count": 0, "learning_count": 0},
            ],
            "edges": [
                {"from_entity": "postgresql", "to_entity": "mongodb", "relationship": "replaces", "confidence": "high"},
            ],
        }
        dot = build_entity_dot_graph(graph_data)
        assert "dashed" in dot  # replaces uses dashed style

    def test_node_colors_by_type(self):
        graph_data = {
            "nodes": [
                {"entity": "fastapi", "entity_type": "technology", "decision_count": 1, "learning_count": 0},
                {"entity": "microservices", "entity_type": "pattern", "decision_count": 1, "learning_count": 0},
            ],
            "edges": [],
        }
        dot = build_entity_dot_graph(graph_data)
        assert "#3B82F6" in dot  # technology blue
        assert "#10B981" in dot  # pattern green
