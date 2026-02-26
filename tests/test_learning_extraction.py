"""Tests for learning extraction from session transcripts."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from setkontext.extraction.learning import (
    _build_session_info,
    _build_title,
    _parse_response,
    extract_session_learnings,
)
from setkontext.extraction.models import Learning


class TestBuildTitle:
    def test_with_prompt(self):
        meta = {"agent": "claude-code", "prompt": "Fix the auth bug"}
        assert _build_title(meta) == "[claude-code] Fix the auth bug"

    def test_with_long_prompt(self):
        meta = {"agent": "cursor", "prompt": "x" * 100}
        title = _build_title(meta)
        assert len(title) <= 90  # "[cursor] " + 80 chars max
        assert title.endswith("...")

    def test_with_summary_fallback(self):
        meta = {"agent": "claude-code", "summary": "Implemented caching layer"}
        assert _build_title(meta) == "[claude-code] Implemented caching layer"

    def test_with_session_id_fallback(self):
        meta = {"agent": "claude-code", "session_id": "abcdef123456"}
        assert _build_title(meta) == "[claude-code] Session abcdef12"

    def test_empty_meta(self):
        assert _build_title({}) == "[unknown] Session unknown"


class TestBuildSessionInfo:
    def test_full_metadata(self):
        meta = {
            "agent": "claude-code",
            "branch": "feature/auth",
            "prompt": "Fix login",
            "summary": "Fixed login bug",
            "files_touched": ["auth.py", "login.py"],
        }
        info = _build_session_info(meta)
        assert "**Agent:** claude-code" in info
        assert "**Branch:** feature/auth" in info
        assert "**Initial Prompt:** Fix login" in info
        assert "**Files Touched:** auth.py, login.py" in info

    def test_empty_metadata(self):
        info = _build_session_info({})
        assert "no session metadata" in info


class TestParseResponse:
    def _make_response(self, text: str) -> MagicMock:
        response = MagicMock()
        content_block = MagicMock()
        content_block.text = text
        response.content = [content_block]
        return response

    def test_valid_response(self):
        data = {
            "learnings": [
                {
                    "category": "bug_fix",
                    "summary": "Fixed timeout issue",
                    "detail": "Changed TTL from seconds to ms",
                    "components": ["auth/session.py"],
                    "entities": [{"name": "redis", "entity_type": "technology"}],
                }
            ]
        }
        response = self._make_response(json.dumps(data))
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 1
        assert learnings[0].category == "bug_fix"
        assert learnings[0].summary == "Fixed timeout issue"
        assert learnings[0].components == ["auth/session.py"]
        assert len(learnings[0].entities) == 1
        assert learnings[0].entities[0].name == "redis"

    def test_empty_learnings(self):
        response = self._make_response('{"learnings": []}')
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 0

    def test_code_fenced_json(self):
        data = '```json\n{"learnings": [{"category": "gotcha", "summary": "Watch out", "detail": "Be careful"}]}\n```'
        response = self._make_response(data)
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 1
        assert learnings[0].category == "gotcha"

    def test_invalid_json(self):
        response = self._make_response("this is not json")
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 0

    def test_empty_response(self):
        response = MagicMock()
        response.content = []
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 0

    def test_invalid_category_skipped(self):
        data = {
            "learnings": [
                {
                    "category": "invalid_category",
                    "summary": "This should be skipped",
                    "detail": "",
                },
                {
                    "category": "gotcha",
                    "summary": "This should be kept",
                    "detail": "",
                },
            ]
        }
        response = self._make_response(json.dumps(data))
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 1
        assert learnings[0].category == "gotcha"

    def test_multiple_learnings(self):
        data = {
            "learnings": [
                {"category": "bug_fix", "summary": "Bug 1", "detail": "Detail 1"},
                {"category": "gotcha", "summary": "Gotcha 1", "detail": "Detail 2"},
                {"category": "implementation", "summary": "Impl 1", "detail": "Detail 3"},
            ]
        }
        response = self._make_response(json.dumps(data))
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 3
        categories = {l.category for l in learnings}
        assert categories == {"bug_fix", "gotcha", "implementation"}

    def test_missing_optional_fields(self):
        data = {
            "learnings": [
                {"category": "bug_fix", "summary": "Minimal learning"}
            ]
        }
        response = self._make_response(json.dumps(data))
        learnings = _parse_response(response, "learning:test")
        assert len(learnings) == 1
        assert learnings[0].detail == ""
        assert learnings[0].components == []
        assert learnings[0].entities == []


class TestExtractSessionLearnings:
    def test_returns_source_and_learnings(self):
        mock_response = MagicMock()
        content_block = MagicMock()
        content_block.text = json.dumps({
            "learnings": [
                {
                    "category": "implementation",
                    "summary": "Built caching layer",
                    "detail": "Used Redis with 5-min TTL",
                    "components": ["cache/redis.py"],
                    "entities": [{"name": "redis", "entity_type": "technology"}],
                }
            ]
        })
        mock_response.content = [content_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        source, learnings = extract_session_learnings(
            transcript="User asked to add caching...",
            repo="acme/webapp",
            client=mock_client,
            session_metadata={"agent": "claude-code", "session_id": "test123"},
        )

        assert source.source_type == "learning"
        assert source.repo == "acme/webapp"
        assert len(learnings) == 1
        assert learnings[0].category == "implementation"
        assert learnings[0].summary == "Built caching layer"

    def test_api_error_returns_empty(self):
        import anthropic

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="Server error",
            request=MagicMock(),
            body=None,
        )

        source, learnings = extract_session_learnings(
            transcript="Some transcript",
            repo="acme/webapp",
            client=mock_client,
        )

        assert source.source_type == "learning"
        assert len(learnings) == 0

    def test_truncates_long_transcript(self):
        mock_response = MagicMock()
        content_block = MagicMock()
        content_block.text = '{"learnings": []}'
        mock_response.content = [content_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        long_transcript = "x" * 20000
        extract_session_learnings(
            transcript=long_transcript,
            repo="acme/webapp",
            client=mock_client,
        )

        # Verify the prompt sent to Claude was truncated
        call_args = mock_client.messages.create.call_args
        prompt_text = call_args.kwargs["messages"][0]["content"]
        assert "truncated" in prompt_text
