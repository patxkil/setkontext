"""Tests for setkontext.query.validator — response parsing and query building."""

from __future__ import annotations

from unittest.mock import MagicMock

from setkontext.query.validator import DecisionValidator, ValidationResult


class TestValidationResult:
    def test_to_json(self):
        result = ValidationResult(
            proposed_approach="Use MongoDB",
            verdict="CONFLICTS",
            recommendation="Use PostgreSQL instead.",
            decisions_checked=3,
        )
        import json
        parsed = json.loads(result.to_json())
        assert parsed["verdict"] == "CONFLICTS"
        assert parsed["recommendation"] == "Use PostgreSQL instead."

    def test_default_fields(self):
        result = ValidationResult(
            proposed_approach="test",
            verdict="NO_COVERAGE",
        )
        assert result.conflicts == []
        assert result.alignments == []
        assert result.warnings == []
        assert result.recommendation == ""
        assert result.decisions_checked == 0


class TestValidatorFtsQuery:
    def _validator(self) -> DecisionValidator:
        v = DecisionValidator.__new__(DecisionValidator)
        v._repo = MagicMock()
        v._client = None
        return v

    def test_strips_planning_stop_words(self):
        v = self._validator()
        query = v._build_fts_query("I plan to use Redis for caching")
        words = [w.strip().lower() for w in query.split("OR")]
        assert "plan" not in words
        assert "redis" in words
        assert "caching" in words

    def test_empty_input(self):
        v = self._validator()
        assert v._build_fts_query("") == ""


class TestValidatorParseResponse:
    def _validator(self) -> DecisionValidator:
        v = DecisionValidator.__new__(DecisionValidator)
        v._repo = MagicMock()
        v._client = None
        return v

    def test_parse_conflicts(self):
        text = '''{
            "verdict": "CONFLICTS",
            "conflicts": [{
                "decision_summary": "Team chose PostgreSQL",
                "source_url": "https://github.com/x/y/pull/5",
                "explanation": "Proposal uses MongoDB which contradicts PostgreSQL decision",
                "severity": "hard"
            }],
            "alignments": [],
            "warnings": ["Consider migration plan"],
            "recommendation": "Use PostgreSQL instead of MongoDB"
        }'''
        result = self._validator()._parse_response(text, "Use MongoDB", 5)
        assert result.verdict == "CONFLICTS"
        assert len(result.conflicts) == 1
        assert result.conflicts[0].severity == "hard"
        assert result.decisions_checked == 5

    def test_parse_aligns(self):
        text = '''{
            "verdict": "ALIGNS",
            "conflicts": [],
            "alignments": ["Consistent with FastAPI decision"],
            "warnings": [],
            "recommendation": "Proceed as planned"
        }'''
        result = self._validator()._parse_response(text, "Use FastAPI", 3)
        assert result.verdict == "ALIGNS"
        assert len(result.alignments) == 1

    def test_parse_with_code_fences(self):
        text = '```json\n{"verdict": "NO_COVERAGE", "conflicts": [], "alignments": [], "warnings": [], "recommendation": "Proceed"}\n```'
        result = self._validator()._parse_response(text, "test", 0)
        assert result.verdict == "NO_COVERAGE"

    def test_parse_invalid_json(self):
        result = self._validator()._parse_response("not json", "test", 2)
        assert result.verdict == "NO_COVERAGE"
        assert result.decisions_checked == 2


class TestValidateNoDecisions:
    def test_returns_no_coverage(self):
        repo_mock = MagicMock()
        repo_mock.search_decisions.return_value = []
        repo_mock.get_entities.return_value = []
        repo_mock.get_all_decisions.return_value = []

        v = DecisionValidator(repo_mock, MagicMock())
        result = v.validate("Use a new framework")
        assert result.verdict == "NO_COVERAGE"
        assert result.decisions_checked == 0
