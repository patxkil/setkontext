"""Tests for setkontext.extraction.pr — parsing helpers (no API calls)."""

from __future__ import annotations

from unittest.mock import MagicMock

from setkontext.extraction.pr import (
    _build_pr_text,
    _format_comments,
    _format_commits,
    _parse_response,
)
from setkontext.github.fetcher import PRData


def _make_pr(**kwargs) -> PRData:
    defaults = dict(
        number=1,
        title="Test PR",
        body="Description",
        url="https://github.com/x/y/pull/1",
        merged_at="2024-06-01",
        review_comments=["LGTM", "Consider using async here"],
        commit_messages=["feat: add endpoint", "fix: handle edge case"],
    )
    defaults.update(kwargs)
    return PRData(**defaults)


class TestBuildPrText:
    def test_includes_title(self):
        pr = _make_pr()
        text = _build_pr_text(pr)
        assert "# Test PR" in text

    def test_includes_body(self):
        pr = _make_pr(body="Added caching layer")
        text = _build_pr_text(pr)
        assert "Added caching layer" in text

    def test_includes_review_comments(self):
        pr = _make_pr(review_comments=["Great approach", "Needs tests"])
        text = _build_pr_text(pr)
        assert "Great approach" in text
        assert "Needs tests" in text

    def test_no_body(self):
        pr = _make_pr(body="")
        text = _build_pr_text(pr)
        assert "# Test PR" in text


class TestFormatComments:
    def test_empty_comments(self):
        assert _format_comments([]) == "(no review comments)"

    def test_formats_as_list(self):
        result = _format_comments(["First", "Second"])
        assert "- First" in result
        assert "- Second" in result

    def test_truncates_long_comments(self):
        long_comments = ["x" * 1000 for _ in range(10)]
        result = _format_comments(long_comments)
        assert "more comments" in result


class TestFormatCommits:
    def test_empty(self):
        assert _format_commits([]) == "(no commit messages)"

    def test_formats_as_list(self):
        result = _format_commits(["feat: add X", "fix: Y"])
        assert "- feat: add X" in result

    def test_limits_to_10(self):
        msgs = [f"commit {i}" for i in range(20)]
        result = _format_commits(msgs)
        lines = [l for l in result.splitlines() if l.startswith("- ")]
        assert len(lines) == 10


class TestParseResponse:
    def _mock_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        content_block = MagicMock()
        content_block.text = text
        resp.content = [content_block]
        return resp

    def test_parse_valid_json(self):
        text = '''{
            "decisions": [{
                "summary": "Chose Redis for caching",
                "reasoning": "Fast in-memory store",
                "alternatives": ["Memcached"],
                "entities": [{"name": "redis", "entity_type": "technology"}],
                "confidence": "high"
            }]
        }'''
        decisions = _parse_response(self._mock_response(text), "pr:5", "2024-01-01")
        assert len(decisions) == 1
        assert decisions[0].summary == "Chose Redis for caching"
        assert decisions[0].entities[0].name == "redis"
        assert decisions[0].confidence == "high"
        assert decisions[0].decision_date == "2024-01-01"

    def test_parse_empty_decisions(self):
        text = '{"decisions": []}'
        decisions = _parse_response(self._mock_response(text), "pr:5", "")
        assert decisions == []

    def test_parse_with_code_fences(self):
        text = '```json\n{"decisions": [{"summary": "Use X", "reasoning": "Y"}]}\n```'
        decisions = _parse_response(self._mock_response(text), "pr:5", "")
        assert len(decisions) == 1
        assert decisions[0].summary == "Use X"

    def test_parse_invalid_json(self):
        decisions = _parse_response(
            self._mock_response("not json at all"), "pr:5", ""
        )
        assert decisions == []

    def test_parse_empty_response(self):
        resp = MagicMock()
        resp.content = []
        decisions = _parse_response(resp, "pr:5", "")
        assert decisions == []

    def test_parse_multiple_decisions(self):
        text = '''{
            "decisions": [
                {"summary": "Use Kafka", "reasoning": "Event streaming", "entities": []},
                {"summary": "Use Avro", "reasoning": "Schema evolution", "entities": []}
            ]
        }'''
        decisions = _parse_response(self._mock_response(text), "pr:10", "2024-03-01")
        assert len(decisions) == 2
        assert decisions[0].source_id == "pr:10"
        assert decisions[1].source_id == "pr:10"
        # Each decision should have a unique id
        assert decisions[0].id != decisions[1].id
