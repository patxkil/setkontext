"""Tests for learning CRUD operations in the repository."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from setkontext.extraction.models import Entity, Learning, Source
from setkontext.storage.repository import Repository


class TestSaveLearning:
    def test_save_and_retrieve(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        learnings = repo.get_recent_learnings(limit=10)
        assert len(learnings) == 1
        assert learnings[0]["summary"] == sample_learning.summary
        assert learnings[0]["category"] == "bug_fix"

    def test_save_with_entities(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        learnings = repo.get_recent_learnings(limit=10)
        entities = learnings[0]["entities"]
        entity_names = {e["entity"] for e in entities}
        assert "jwt" in entity_names
        assert "redis" in entity_names

    def test_save_with_components(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        learnings = repo.get_recent_learnings(limit=10)
        assert "auth/session.py" in learnings[0]["components"]
        assert "auth/middleware.py" in learnings[0]["components"]

    def test_upsert_replaces(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])

        # Save again with updated summary
        updated = Learning(
            id=sample_learning.id,
            source_id=sample_learning.source_id,
            category="bug_fix",
            summary="Updated summary",
            detail="Updated detail",
            components=[],
            entities=[],
            session_date="2024-08-10",
            extracted_at=datetime.now(),
        )
        repo.save_learning(updated)

        learnings = repo.get_recent_learnings(limit=10)
        assert len(learnings) == 1
        assert learnings[0]["summary"] == "Updated summary"


class TestSearchLearnings:
    @pytest.fixture(autouse=True)
    def setup_data(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning, sample_gotcha: Learning):
        # Save the gotcha's source too
        gotcha_source = Source(
            id="learning:session-def456",
            source_type="learning",
            repo="acme/webapp",
            url="",
            title="[claude-code] JSONB index gotcha",
            raw_content="Discovered JSONB index issue.",
            fetched_at=datetime(2024, 8, 12, 10, 0, 0),
        )
        repo.save_learning_result(sample_learning_source, [sample_learning])
        repo.save_learning_result(gotcha_source, [sample_gotcha])
        self.repo = repo

    def test_fts_search(self):
        results = self.repo.search_learnings("timeout")
        assert len(results) >= 1
        assert any("timeout" in r["summary"].lower() for r in results)

    def test_fts_search_detail(self):
        results = self.repo.search_learnings("milliseconds")
        assert len(results) >= 1

    def test_search_with_category_filter(self):
        results = self.repo.search_learnings("timeout OR jsonb", category="gotcha")
        # Should only return the gotcha, not the bug_fix
        for r in results:
            assert r["category"] == "gotcha"

    def test_search_no_results(self):
        results = self.repo.search_learnings("nonexistent_xyz_term")
        assert len(results) == 0


class TestGetRecentLearnings:
    @pytest.fixture(autouse=True)
    def setup_data(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning, sample_gotcha: Learning):
        gotcha_source = Source(
            id="learning:session-def456",
            source_type="learning",
            repo="acme/webapp",
            url="",
            title="[claude-code] JSONB index gotcha",
            raw_content="Discovered JSONB index issue.",
            fetched_at=datetime(2024, 8, 12, 10, 0, 0),
        )
        repo.save_learning_result(sample_learning_source, [sample_learning])
        repo.save_learning_result(gotcha_source, [sample_gotcha])
        self.repo = repo

    def test_get_all_recent(self):
        results = self.repo.get_recent_learnings(limit=10)
        assert len(results) == 2

    def test_filter_by_category(self):
        results = self.repo.get_recent_learnings(limit=10, category="bug_fix")
        assert len(results) == 1
        assert results[0]["category"] == "bug_fix"

    def test_limit(self):
        results = self.repo.get_recent_learnings(limit=1)
        assert len(results) == 1


class TestGetLearningsByEntity:
    def test_entity_lookup(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        results = repo.get_learnings_by_entity("jwt")
        assert len(results) == 1
        assert results[0]["summary"] == sample_learning.summary

    def test_case_insensitive(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        results = repo.get_learnings_by_entity("JWT")
        assert len(results) == 1

    def test_no_match(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        results = repo.get_learnings_by_entity("graphql")
        assert len(results) == 0


class TestLearningStats:
    def test_empty_stats(self, repo: Repository):
        stats = repo.get_learning_stats()
        assert stats["total_learnings"] == 0
        assert stats["bug_fixes"] == 0
        assert stats["gotchas"] == 0
        assert stats["implementations"] == 0

    def test_stats_with_data(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning, sample_gotcha: Learning):
        gotcha_source = Source(
            id="learning:session-def456",
            source_type="learning",
            repo="acme/webapp",
            url="",
            title="[claude-code] JSONB gotcha",
            raw_content="JSONB issue.",
            fetched_at=datetime(2024, 8, 12, 10, 0, 0),
        )
        repo.save_learning_result(sample_learning_source, [sample_learning])
        repo.save_learning_result(gotcha_source, [sample_gotcha])

        stats = repo.get_learning_stats()
        assert stats["total_learnings"] == 2
        assert stats["bug_fixes"] == 1
        assert stats["gotchas"] == 1
        assert stats["implementations"] == 0

    def test_stats_in_get_stats(self, repo: Repository, sample_learning_source: Source, sample_learning: Learning):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        stats = repo.get_stats()
        assert "total_learnings" in stats
        assert stats["total_learnings"] == 1
        assert stats["bug_fixes"] == 1
