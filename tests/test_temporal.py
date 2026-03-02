"""Tests for temporal (date range) queries and timeline."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from setkontext.extraction.models import Decision, Entity, Learning, Source
from setkontext.storage.repository import Repository


@pytest.fixture
def dated_repo(repo: Repository) -> Repository:
    """Repository with decisions and learnings at different dates."""
    # Source
    source = Source(
        id="pr:100",
        source_type="pr",
        repo="acme/webapp",
        url="https://github.com/acme/webapp/pull/100",
        title="Add caching",
        raw_content="Added Redis caching.",
        fetched_at=datetime(2024, 1, 15),
    )
    repo.save_source(source)

    # Decision in January
    d1 = Decision(
        id=str(uuid.uuid4()),
        source_id=source.id,
        summary="Use Redis for caching",
        reasoning="Fast and simple.",
        entities=[Entity(name="redis", entity_type="technology")],
        confidence="high",
        decision_date="2024-01-15",
        extracted_at=datetime(2024, 1, 15),
    )
    repo.save_decision(d1)

    # Decision in March
    source2 = Source(
        id="pr:200",
        source_type="pr",
        repo="acme/webapp",
        url="https://github.com/acme/webapp/pull/200",
        title="Switch to Postgres",
        raw_content="PostgreSQL chosen.",
        fetched_at=datetime(2024, 3, 10),
    )
    repo.save_source(source2)
    d2 = Decision(
        id=str(uuid.uuid4()),
        source_id=source2.id,
        summary="Use PostgreSQL for main DB",
        reasoning="Strong consistency.",
        entities=[Entity(name="postgresql", entity_type="technology")],
        confidence="high",
        decision_date="2024-03-10",
        extracted_at=datetime(2024, 3, 10),
    )
    repo.save_decision(d2)

    # Learning in February
    learn_source = Source(
        id="learning:sess-1",
        source_type="learning",
        repo="acme/webapp",
        url="",
        title="Bug fix session",
        raw_content="Fixed cache bug.",
        fetched_at=datetime(2024, 2, 20),
    )
    repo.save_source(learn_source)
    l1 = Learning(
        id=str(uuid.uuid4()),
        source_id=learn_source.id,
        category="bug_fix",
        summary="Fixed Redis cache TTL bug",
        detail="TTL was in seconds, not milliseconds.",
        components=["cache/redis.py"],
        entities=[Entity(name="redis", entity_type="technology")],
        session_date="2024-02-20",
        extracted_at=datetime(2024, 2, 20),
    )
    repo.save_learning(l1)

    return repo


class TestDecisionsInRange:
    def test_full_range(self, dated_repo: Repository):
        results = dated_repo.get_decisions_in_range("2024-01-01", "2024-12-31")
        assert len(results) == 2

    def test_narrow_range(self, dated_repo: Repository):
        results = dated_repo.get_decisions_in_range("2024-01-01", "2024-02-01")
        assert len(results) == 1
        assert "Redis" in results[0]["summary"]

    def test_no_results(self, dated_repo: Repository):
        results = dated_repo.get_decisions_in_range("2025-01-01", "2025-12-31")
        assert len(results) == 0


class TestLearningsInRange:
    def test_finds_learning_in_range(self, dated_repo: Repository):
        results = dated_repo.get_learnings_in_range("2024-02-01", "2024-02-28")
        assert len(results) == 1
        assert "Redis" in results[0]["summary"]

    def test_no_results(self, dated_repo: Repository):
        results = dated_repo.get_learnings_in_range("2025-01-01", "2025-12-31")
        assert len(results) == 0


class TestTimeline:
    def test_merged_and_sorted(self, dated_repo: Repository):
        timeline = dated_repo.get_timeline(limit=50)
        assert len(timeline) == 3  # 2 decisions + 1 learning
        # Should be sorted newest first
        dates = [item["_date"] for item in timeline]
        assert dates == sorted(dates, reverse=True)

    def test_type_annotation(self, dated_repo: Repository):
        timeline = dated_repo.get_timeline(limit=50)
        types_found = {item["_type"] for item in timeline}
        assert "decision" in types_found
        assert "learning" in types_found

    def test_limit(self, dated_repo: Repository):
        timeline = dated_repo.get_timeline(limit=1)
        assert len(timeline) == 1
