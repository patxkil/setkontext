"""Tests for setkontext.context — context file generation."""

from __future__ import annotations

from unittest.mock import MagicMock

from setkontext.context import generate_context


def _mock_repo(decisions=None, entities=None, stats=None) -> MagicMock:
    repo = MagicMock()
    repo.get_all_decisions.return_value = decisions or []
    repo.get_entities.return_value = entities or []
    repo.get_stats.return_value = stats or {
        "total_sources": 0,
        "total_decisions": 0,
        "unique_entities": 0,
        "pr_sources": 0,
        "adr_sources": 0,
        "doc_sources": 0,
        "session_sources": 0,
    }
    return repo


class TestGenerateContextEmpty:
    def test_no_decisions(self):
        repo = _mock_repo()
        result = generate_context(repo)
        assert "No engineering decisions extracted yet" in result
        assert "setkontext extract" in result


class TestGenerateContextWithData:
    def _populated_repo(self) -> MagicMock:
        decisions = [
            {
                "summary": "Use FastAPI for web framework",
                "reasoning": "Async support and auto-docs",
                "alternatives": ["Flask", "Django"],
                "confidence": "high",
                "source_url": "https://github.com/x/y/pull/1",
                "source_type": "pr",
            },
            {
                "summary": "Use PostgreSQL for primary datastore",
                "reasoning": "ACID compliance needed",
                "alternatives": ["MySQL"],
                "confidence": "high",
                "source_url": "https://github.com/x/y/blob/main/docs/adr/001.md",
                "source_type": "adr",
            },
            {
                "summary": "Deploy on AWS ECS",
                "reasoning": "Team familiarity",
                "alternatives": [],
                "confidence": "medium",
                "source_url": "https://github.com/x/y/pull/10",
                "source_type": "pr",
            },
        ]
        entities = [
            {"entity": "fastapi", "entity_type": "technology", "decision_count": 2},
            {"entity": "postgresql", "entity_type": "technology", "decision_count": 1},
            {"entity": "microservice", "entity_type": "pattern", "decision_count": 1},
        ]
        stats = {
            "total_sources": 5,
            "total_decisions": 3,
            "unique_entities": 3,
            "pr_sources": 3,
            "adr_sources": 1,
            "doc_sources": 1,
            "session_sources": 0,
        }
        return _mock_repo(decisions, entities, stats)

    def test_claude_format_has_header(self):
        result = generate_context(self._populated_repo(), format="claude")
        assert "Engineering Decisions Context" in result

    def test_cursor_format_has_header(self):
        result = generate_context(self._populated_repo(), format="cursor")
        assert "Project Engineering Decisions" in result

    def test_includes_tech_stack(self):
        result = generate_context(self._populated_repo())
        assert "fastapi" in result
        assert "postgresql" in result

    def test_includes_patterns(self):
        result = generate_context(self._populated_repo())
        assert "microservice" in result

    def test_groups_by_confidence(self):
        result = generate_context(self._populated_repo())
        assert "High Confidence" in result
        assert "Medium Confidence" in result

    def test_includes_decision_summaries(self):
        result = generate_context(self._populated_repo())
        assert "FastAPI" in result
        assert "PostgreSQL" in result
        assert "AWS ECS" in result

    def test_includes_reasoning(self):
        result = generate_context(self._populated_repo())
        assert "Async support" in result

    def test_includes_rejected_alternatives(self):
        result = generate_context(self._populated_repo())
        assert "Flask" in result

    def test_includes_source_urls(self):
        result = generate_context(self._populated_repo())
        assert "github.com" in result

    def test_includes_stats_footer(self):
        result = generate_context(self._populated_repo())
        assert "5 sources" in result
        assert "3 decisions" in result
