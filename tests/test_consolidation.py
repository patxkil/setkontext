"""Tests for the consolidation pipeline: learnings -> decisions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from setkontext.extraction.consolidation import (
    ConsolidationProposal,
    _format_learnings,
    _parse_response,
    create_consolidation_source,
    find_consolidation_proposals,
)
from setkontext.extraction.models import Decision, Entity, Learning, Source
from setkontext.storage.repository import Repository


# ── Fixtures ──────────────────────────────────────────────────────


def _make_learning(
    source_id: str,
    category: str,
    summary: str,
    entities: list[Entity],
    detail: str = "",
    components: list[str] | None = None,
) -> Learning:
    return Learning(
        id=str(uuid.uuid4()),
        source_id=source_id,
        category=category,
        summary=summary,
        detail=detail,
        components=components or [],
        entities=entities,
        session_date="2026-03-06",
        extracted_at=datetime.now(),
    )


def _make_source(source_id: str) -> Source:
    return Source(
        id=source_id,
        source_type="learning",
        repo="acme/webapp",
        url="",
        title=f"[claude-code] Session {source_id}",
        raw_content="transcript...",
        fetched_at=datetime.now(),
    )


# ── Repository Cluster Detection ─────────────────────────────────


class TestGetLearningClusters:
    def test_no_learnings(self, repo: Repository):
        clusters = repo.get_learning_clusters()
        assert clusters == []

    def test_single_learning_no_cluster(self, repo: Repository):
        source = _make_source("learning:s1")
        learning = _make_learning(
            "learning:s1", "bug_fix", "Fixed redis timeout",
            [Entity("redis", "technology")],
        )
        repo.save_learning_result(source, [learning])
        clusters = repo.get_learning_clusters(min_count=2)
        assert clusters == []

    def test_two_learnings_same_entity_forms_cluster(self, repo: Repository):
        s1 = _make_source("learning:s1")
        s2 = _make_source("learning:s2")
        l1 = _make_learning(
            "learning:s1", "bug_fix", "Redis timeout issue",
            [Entity("redis", "technology")],
        )
        l2 = _make_learning(
            "learning:s2", "gotcha", "Redis connection pool exhaustion",
            [Entity("redis", "technology")],
        )
        repo.save_learning_result(s1, [l1])
        repo.save_learning_result(s2, [l2])

        clusters = repo.get_learning_clusters(min_count=2)
        assert len(clusters) == 1
        assert clusters[0]["entity"] == "redis"
        assert clusters[0]["learning_count"] == 2
        assert len(clusters[0]["learnings"]) == 2

    def test_min_count_threshold(self, repo: Repository):
        s1 = _make_source("learning:s1")
        s2 = _make_source("learning:s2")
        l1 = _make_learning("learning:s1", "bug_fix", "Issue 1", [Entity("redis", "technology")])
        l2 = _make_learning("learning:s2", "gotcha", "Issue 2", [Entity("redis", "technology")])
        repo.save_learning_result(s1, [l1])
        repo.save_learning_result(s2, [l2])

        # min_count=3 should find nothing
        assert repo.get_learning_clusters(min_count=3) == []
        # min_count=2 should find redis
        assert len(repo.get_learning_clusters(min_count=2)) == 1

    def test_cluster_includes_existing_decision_count(self, repo: Repository):
        # Add a decision for redis
        d_source = Source(
            id="pr:99", source_type="pr", repo="acme/webapp",
            url="", title="Use Redis", raw_content="", fetched_at=datetime.now(),
        )
        decision = Decision(
            id=str(uuid.uuid4()), source_id="pr:99",
            summary="Use Redis for caching", reasoning="Fast",
            entities=[Entity("redis", "technology")], confidence="high",
        )
        repo.save_extraction_result(d_source, [decision])

        # Add learnings for redis
        s1 = _make_source("learning:s1")
        s2 = _make_source("learning:s2")
        l1 = _make_learning("learning:s1", "bug_fix", "Redis issue 1", [Entity("redis", "technology")])
        l2 = _make_learning("learning:s2", "gotcha", "Redis issue 2", [Entity("redis", "technology")])
        repo.save_learning_result(s1, [l1])
        repo.save_learning_result(s2, [l2])

        clusters = repo.get_learning_clusters(min_count=2)
        assert clusters[0]["existing_decision_count"] == 1


# ── Consolidation LLM Response Parsing ───────────────────────────


class TestParseResponse:
    def _make_response(self, text: str) -> MagicMock:
        response = MagicMock()
        content_block = MagicMock()
        content_block.text = text
        response.content = [content_block]
        return response

    def test_valid_proposal(self):
        data = {
            "proposals": [
                {
                    "summary": "Use Redis with connection pooling for all cache operations",
                    "reasoning": "Multiple sessions hit Redis connection issues",
                    "alternatives": ["Memcached", "In-process cache"],
                    "entities": [{"name": "redis", "entity_type": "technology"}],
                    "confidence": "high",
                    "source_learning_ids": ["id1", "id2"],
                    "rationale": "Three sessions encountered Redis connection issues",
                }
            ]
        }
        response = self._make_response(json.dumps(data))
        proposals = _parse_response(response, "redis")

        assert len(proposals) == 1
        p = proposals[0]
        assert p.decision.summary == "Use Redis with connection pooling for all cache operations"
        assert p.decision.confidence == "high"
        assert len(p.decision.entities) == 1
        assert p.source_learning_ids == ["id1", "id2"]
        assert "Three sessions" in p.rationale

    def test_no_proposals(self):
        response = self._make_response('{"proposals": []}')
        proposals = _parse_response(response, "redis")
        assert proposals == []

    def test_code_fenced_json(self):
        data = '```json\n{"proposals": [{"summary": "Test", "reasoning": "R", "confidence": "medium", "source_learning_ids": []}]}\n```'
        response = self._make_response(data)
        proposals = _parse_response(response, "test")
        assert len(proposals) == 1

    def test_invalid_json(self):
        response = self._make_response("not json at all")
        proposals = _parse_response(response, "test")
        assert proposals == []

    def test_empty_response(self):
        response = MagicMock()
        response.content = []
        proposals = _parse_response(response, "test")
        assert proposals == []

    def test_multiple_proposals(self):
        data = {
            "proposals": [
                {"summary": "Decision 1", "reasoning": "R1", "confidence": "high", "source_learning_ids": ["a"]},
                {"summary": "Decision 2", "reasoning": "R2", "confidence": "medium", "source_learning_ids": ["b"]},
            ]
        }
        response = self._make_response(json.dumps(data))
        proposals = _parse_response(response, "entity")
        assert len(proposals) == 2
        assert proposals[0].decision.summary == "Decision 1"
        assert proposals[1].decision.summary == "Decision 2"


# ── Format Learnings ─────────────────────────────────────────────


class TestFormatLearnings:
    def test_formats_learnings_for_prompt(self):
        learnings = [
            {
                "id": "abc123",
                "category": "bug_fix",
                "summary": "Fixed timeout",
                "detail": "Changed TTL calc",
                "components": ["auth.py"],
                "session_date": "2026-03-01",
            },
            {
                "id": "def456",
                "category": "gotcha",
                "summary": "Pool exhaustion",
                "detail": "Need max_connections=20",
                "components": ["db.py", "config.py"],
                "session_date": "2026-03-02",
            },
        ]
        text = _format_learnings(learnings)
        assert "Learning 1 [BUG FIX]" in text
        assert "Learning 2 [GOTCHA]" in text
        assert "abc123" in text
        assert "Fixed timeout" in text
        assert "Pool exhaustion" in text


# ── Create Consolidation Source ──────────────────────────────────


class TestCreateConsolidationSource:
    def test_creates_source(self):
        decision = Decision(
            id="d1", source_id="consolidation:abc",
            summary="Use Redis with pooling", reasoning="Pattern found",
        )
        proposal = ConsolidationProposal(
            decision=decision,
            source_learning_ids=["l1", "l2", "l3"],
            rationale="Recurring pattern",
        )
        source = create_consolidation_source(proposal, "acme/webapp")

        assert source.id == "consolidation:abc"
        assert source.source_type == "consolidation"
        assert source.repo == "acme/webapp"
        assert "consolidated" in source.title.lower()
        assert "l1" in source.raw_content
        assert "Recurring pattern" in source.raw_content


# ── End-to-End Consolidation ─────────────────────────────────────


class TestFindConsolidationProposals:
    def test_with_mock_client(self):
        clusters = [
            {
                "entity": "redis",
                "entity_type": "technology",
                "learning_count": 2,
                "existing_decision_count": 0,
                "learnings": [
                    {
                        "id": "l1", "category": "bug_fix",
                        "summary": "Redis timeout", "detail": "Fixed TTL",
                        "components": ["cache.py"], "session_date": "2026-03-01",
                    },
                    {
                        "id": "l2", "category": "gotcha",
                        "summary": "Redis pool exhaustion", "detail": "Set max_connections",
                        "components": ["db.py"], "session_date": "2026-03-02",
                    },
                ],
            }
        ]

        mock_response = MagicMock()
        content_block = MagicMock()
        content_block.text = json.dumps({
            "proposals": [
                {
                    "summary": "Configure Redis with connection pooling (max 20)",
                    "reasoning": "Two sessions hit connection issues",
                    "alternatives": ["Memcached"],
                    "entities": [{"name": "redis", "entity_type": "technology"}],
                    "confidence": "medium",
                    "source_learning_ids": ["l1", "l2"],
                    "rationale": "Recurring Redis connection pattern",
                }
            ]
        })
        mock_response.content = [content_block]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        proposals = find_consolidation_proposals(clusters, mock_client)

        assert len(proposals) == 1
        assert proposals[0].decision.summary == "Configure Redis with connection pooling (max 20)"
        assert proposals[0].source_learning_ids == ["l1", "l2"]

    def test_empty_clusters(self):
        mock_client = MagicMock()
        proposals = find_consolidation_proposals([], mock_client)
        assert proposals == []
        mock_client.messages.create.assert_not_called()

    def test_api_error_returns_empty(self):
        import anthropic

        clusters = [
            {
                "entity": "redis", "entity_type": "technology",
                "learning_count": 2, "existing_decision_count": 0,
                "learnings": [
                    {"id": "l1", "category": "bug_fix", "summary": "Issue",
                     "detail": "", "components": [], "session_date": "2026-03-01"},
                ],
            }
        ]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="Server error", request=MagicMock(), body=None,
        )

        proposals = find_consolidation_proposals(clusters, mock_client)
        assert proposals == []


# ── Saving Consolidated Decisions ────────────────────────────────


class TestSaveConsolidatedDecision:
    def test_save_and_retrieve(self, repo: Repository):
        """End-to-end: create proposal, save source + decision, retrieve."""
        decision = Decision(
            id=str(uuid.uuid4()),
            source_id="consolidation:test123",
            summary="Always use connection pooling with Redis",
            reasoning="Multiple sessions encountered connection exhaustion",
            alternatives=["No pooling", "Memcached"],
            entities=[Entity("redis", "technology")],
            confidence="high",
            decision_date="2026-03-06",
        )
        proposal = ConsolidationProposal(
            decision=decision,
            source_learning_ids=["l1", "l2"],
            rationale="Recurring pattern",
        )
        source = create_consolidation_source(proposal, "acme/webapp")
        repo.save_extraction_result(source, [decision])

        # Verify it's retrievable
        decisions = repo.get_decisions_by_entity("redis")
        assert len(decisions) == 1
        assert decisions[0]["summary"] == "Always use connection pooling with Redis"
        assert decisions[0]["source_type"] == "consolidation"

        # Verify it shows up in stats
        stats = repo.get_stats()
        assert stats["total_decisions"] == 1
