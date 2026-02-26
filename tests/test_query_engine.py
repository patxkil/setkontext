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


class TestChat:
    def test_chat_no_decisions(self):
        repo_mock = MagicMock()
        repo_mock.search_decisions.return_value = []
        repo_mock.get_entities.return_value = []
        repo_mock.get_all_decisions.return_value = []

        engine = QueryEngine(repo_mock, MagicMock())
        result = engine.chat("Something with no matches", [])
        assert "No relevant engineering decisions" in result.answer
        assert result.decisions == []

    def test_chat_with_history(self):
        decision = {
            "id": "1", "summary": "Use FastAPI", "reasoning": "Async",
            "confidence": "high", "source_url": "", "source_type": "pr",
            "alternatives": [], "entities": [],
        }
        repo_mock = MagicMock()
        # FTS query for "Why did we choose it?" strips to empty,
        # so it falls through to get_all_decisions
        repo_mock.search_decisions.return_value = []
        repo_mock.get_entities.return_value = []
        repo_mock.get_all_decisions.return_value = [decision]

        mock_response = MagicMock()
        content_block = MagicMock()
        content_block.text = "FastAPI was chosen for async support."
        mock_response.content = [content_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        engine = QueryEngine(repo_mock, mock_client)
        history = [
            {"role": "user", "content": "What framework do we use?"},
            {"role": "assistant", "content": "We use FastAPI."},
        ]
        result = engine.chat("Why did we choose it?", history)

        assert result.answer == "FastAPI was chosen for async support."
        assert len(result.decisions) == 1

        # Verify the prompt includes history
        call_args = mock_client.messages.create.call_args
        prompt_text = call_args.kwargs["messages"][0]["content"]
        assert "What framework do we use?" in prompt_text
        assert "Conversation History" in prompt_text

    def test_format_history_empty(self):
        engine = QueryEngine.__new__(QueryEngine)
        engine._repo = MagicMock()
        engine._client = None
        assert engine._format_history([]) == "(No previous conversation)"

    def test_format_history_truncates_long_messages(self):
        engine = QueryEngine.__new__(QueryEngine)
        engine._repo = MagicMock()
        engine._client = None
        history = [{"role": "user", "content": "x" * 1000}]
        result = engine._format_history(history)
        assert "..." in result
        assert len(result) < 600

    def test_format_history_limits_to_10_turns(self):
        engine = QueryEngine.__new__(QueryEngine)
        engine._repo = MagicMock()
        engine._client = None
        history = [{"role": "user", "content": f"Message {i}"} for i in range(20)]
        result = engine._format_history(history)
        # Should only include messages 10-19
        assert "Message 10" in result
        assert "Message 0" not in result
