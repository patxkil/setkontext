"""Tests for setkontext.query.engine — query building and result formatting."""

from __future__ import annotations

from unittest.mock import MagicMock

from setkontext.query.engine import QueryEngine, QueryResult


class TestQueryResult:
    def test_to_text_with_sources(self):
        result = QueryResult(
            question="Why FastAPI?",
            answer="Because of async support.",
            decisions=[
                {
                    "summary": "Chose FastAPI",
                    "confidence": "high",
                    "source_url": "https://github.com/x/y/pull/1",
                }
            ],
            sources_searched=1,
        )
        text = result.to_text()
        assert "Because of async support." in text
        assert "Sources:" in text
        assert "[high] Chose FastAPI" in text

    def test_to_text_no_sources(self):
        result = QueryResult(
            question="Why?",
            answer="No info.",
            decisions=[],
            sources_searched=0,
        )
        text = result.to_text()
        assert "No info." in text
        assert "Sources:" not in text

    def test_to_json(self):
        result = QueryResult(question="Q", answer="A", decisions=[], sources_searched=0)
        import json
        parsed = json.loads(result.to_json())
        assert parsed["question"] == "Q"
        assert parsed["answer"] == "A"


class TestBuildFtsQuery:
    def _engine(self) -> QueryEngine:
        engine = QueryEngine.__new__(QueryEngine)
        engine._repo = MagicMock()
        engine._client = None
        return engine

    def test_strips_stop_words(self):
        engine = self._engine()
        query = engine._build_fts_query("why did we choose FastAPI for the API?")
        assert "why" not in query.lower().split(" or ")
        assert "fastapi" in query.lower()

    def test_strips_short_words(self):
        engine = self._engine()
        query = engine._build_fts_query("is it ok to use Go?")
        # "is", "it", "ok", "to" are stop words or <= 2 chars
        # "go" is only 2 chars, should be stripped
        assert "go" not in query.lower().split(" or ")

    def test_joins_with_or(self):
        engine = self._engine()
        query = engine._build_fts_query("PostgreSQL migration strategy")
        assert " OR " in query

    def test_empty_question(self):
        engine = self._engine()
        assert self._engine()._build_fts_query("") == ""

    def test_all_stop_words(self):
        engine = self._engine()
        assert engine._build_fts_query("why did we do this?") == ""


class TestExtractQueryEntities:
    def test_finds_known_entities(self):
        engine = QueryEngine.__new__(QueryEngine)
        engine._repo = MagicMock()
        engine._repo.get_entities.return_value = [
            {"entity": "fastapi"},
            {"entity": "postgresql"},
        ]
        engine._client = None

        result = engine._extract_query_entities("Why did we choose fastapi?")
        assert "fastapi" in result

    def test_no_match(self):
        engine = QueryEngine.__new__(QueryEngine)
        engine._repo = MagicMock()
        engine._repo.get_entities.return_value = [{"entity": "fastapi"}]
        engine._client = None

        result = engine._extract_query_entities("What database do we use?")
        assert result == []


class TestQueryNoDecisions:
    def test_returns_no_results_message(self):
        repo_mock = MagicMock()
        repo_mock.search_decisions.return_value = []
        repo_mock.get_entities.return_value = []
        repo_mock.get_all_decisions.return_value = []

        engine = QueryEngine(repo_mock, MagicMock())
        result = engine.query("Something with no matches")
        assert "No relevant engineering decisions" in result.answer
        assert result.decisions == []
