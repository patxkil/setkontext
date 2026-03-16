"""Tests for source deduplication (P0.6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from setkontext.extraction.models import Decision, Entity, Source
from setkontext.storage.repository import Repository


def _source(id: str, source_type: str = "pr") -> Source:
    return Source(
        id=id,
        source_type=source_type,
        repo="acme/app",
        url=f"https://github.com/acme/app/{id}",
        title=f"Source {id}",
        raw_content="content",
        fetched_at=datetime(2024, 6, 15),
    )


def _decision(
    source_id: str,
    summary: str,
    confidence: str = "medium",
    entities: list[Entity] | None = None,
) -> Decision:
    return Decision(
        id=str(uuid.uuid4()),
        source_id=source_id,
        summary=summary,
        reasoning="Some reasoning",
        alternatives=[],
        entities=entities or [],
        confidence=confidence,
        decision_date="2024-06-15",
        extracted_at=datetime(2024, 6, 15),
    )


class TestFindDuplicates:
    def test_no_decisions(self, repo: Repository):
        assert repo.find_duplicate_decisions() == []

    def test_no_duplicates(self, repo: Repository):
        s = _source("pr:1")
        repo.save_extraction_result(s, [
            _decision("pr:1", "Use PostgreSQL for the database"),
            _decision("pr:1", "Adopt React for the frontend"),
        ])
        assert repo.find_duplicate_decisions() == []

    def test_finds_exact_duplicates(self, repo: Repository):
        s1 = _source("pr:1")
        s2 = _source("adr:001", "adr")
        repo.save_extraction_result(s1, [
            _decision("pr:1", "Use PostgreSQL as the primary datastore"),
        ])
        repo.save_extraction_result(s2, [
            _decision("adr:001", "Use PostgreSQL as the primary datastore"),
        ])
        groups = repo.find_duplicate_decisions()
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_finds_similar_summaries(self, repo: Repository):
        s1 = _source("pr:1")
        s2 = _source("pr:2")
        repo.save_extraction_result(s1, [
            _decision("pr:1", "Adopted PostgreSQL as the primary database"),
        ])
        repo.save_extraction_result(s2, [
            _decision("pr:2", "Use PostgreSQL as the primary database for persistence"),
        ])
        groups = repo.find_duplicate_decisions(threshold=0.5)
        assert len(groups) == 1

    def test_respects_threshold(self, repo: Repository):
        s1 = _source("pr:1")
        s2 = _source("pr:2")
        repo.save_extraction_result(s1, [
            _decision("pr:1", "Adopted PostgreSQL as the primary database"),
        ])
        repo.save_extraction_result(s2, [
            _decision("pr:2", "Use React with TypeScript for the frontend"),
        ])
        # Very different summaries should not match even at low threshold
        groups = repo.find_duplicate_decisions(threshold=0.5)
        assert len(groups) == 0

    def test_groups_three_duplicates(self, repo: Repository):
        for i in range(3):
            s = _source(f"pr:{i}")
            repo.save_extraction_result(s, [
                _decision(f"pr:{i}", "Use PostgreSQL as the primary datastore"),
            ])
        groups = repo.find_duplicate_decisions()
        assert len(groups) == 1
        assert len(groups[0]) == 3


class TestMergeDuplicates:
    def test_merge_transfers_entities(self, repo: Repository):
        s1 = _source("pr:1")
        s2 = _source("adr:001", "adr")
        d1 = _decision("pr:1", "Use PostgreSQL", entities=[
            Entity(name="postgresql", entity_type="technology"),
        ])
        d2 = _decision("adr:001", "Use PostgreSQL", entities=[
            Entity(name="postgresql", entity_type="technology"),
            Entity(name="mysql", entity_type="technology"),
        ])
        repo.save_extraction_result(s1, [d1])
        repo.save_extraction_result(s2, [d2])

        removed = repo.merge_duplicate_decisions(d1.id, [d2.id])
        assert removed == 1

        # d1 should now have both entities
        decisions = repo.get_decisions_by_entity("mysql")
        assert len(decisions) == 1
        assert decisions[0]["id"] == d1.id

    def test_merge_removes_duplicates(self, repo: Repository):
        s = _source("pr:1")
        d1 = _decision("pr:1", "Use PostgreSQL", confidence="high")
        d2 = _decision("pr:1", "Use PostgreSQL", confidence="low")
        repo.save_extraction_result(s, [d1, d2])

        repo.merge_duplicate_decisions(d1.id, [d2.id])

        all_decisions = repo.get_all_decisions()
        assert len(all_decisions) == 1
        assert all_decisions[0]["id"] == d1.id

    def test_merge_empty_remove_list(self, repo: Repository):
        assert repo.merge_duplicate_decisions("any-id", []) == 0

    def test_merge_transfers_file_references(self, repo: Repository):
        s1 = _source("pr:1")
        s2 = _source("pr:2")
        d1 = _decision("pr:1", "Use PostgreSQL")
        d2 = _decision("pr:2", "Use PostgreSQL")
        repo.save_extraction_result(s1, [d1])
        repo.save_extraction_result(s2, [d2])
        repo.save_file_references("decision", d2.id, ["db/schema.sql"])

        repo.merge_duplicate_decisions(d1.id, [d2.id])

        # File refs should be on d1 now
        items = repo.get_items_by_file("db/schema.sql")
        assert len(items) == 1
        assert items[0]["id"] == d1.id
