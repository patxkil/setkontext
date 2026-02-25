"""Tests for setkontext.storage (db + repository)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from setkontext.extraction.models import Decision, Entity, Source
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository


class TestDatabase:
    def test_creates_tables(self, db_conn: sqlite3.Connection):
        tables = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        assert "sources" in table_names
        assert "decisions" in table_names
        assert "decision_entities" in table_names
        assert "decisions_fts" in table_names

    def test_wal_mode(self, db_conn: sqlite3.Connection):
        mode = db_conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_on(self, db_conn: sqlite3.Connection):
        fk = db_conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_idempotent_schema(self, db_path: Path):
        conn1 = get_connection(db_path)
        conn1.close()
        conn2 = get_connection(db_path)
        tables = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn2.close()
        assert len(tables) > 0


class TestRepositorySaveAndGet:
    def test_save_source(self, repo: Repository, sample_source: Source):
        repo.save_source(sample_source)
        row = repo._conn.execute(
            "SELECT * FROM sources WHERE id = ?", (sample_source.id,)
        ).fetchone()
        assert row is not None
        assert row["source_type"] == "pr"
        assert row["repo"] == "acme/webapp"

    def test_save_decision(
        self, repo: Repository, sample_source: Source, sample_decision: Decision
    ):
        repo.save_source(sample_source)
        repo.save_decision(sample_decision)

        row = repo._conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (sample_decision.id,)
        ).fetchone()
        assert row is not None
        assert row["summary"] == sample_decision.summary
        assert row["confidence"] == "high"
        assert json.loads(row["alternatives"]) == ["Flask", "Django REST Framework"]

    def test_save_decision_entities(
        self, repo: Repository, sample_source: Source, sample_decision: Decision
    ):
        repo.save_source(sample_source)
        repo.save_decision(sample_decision)

        entities = repo._conn.execute(
            "SELECT entity, entity_type FROM decision_entities WHERE decision_id = ?",
            (sample_decision.id,),
        ).fetchall()
        entity_names = {row["entity"] for row in entities}
        assert "fastapi" in entity_names
        assert "flask" in entity_names

    def test_save_extraction_result(
        self, repo: Repository, sample_source: Source, sample_decision: Decision
    ):
        repo.save_extraction_result(sample_source, [sample_decision])

        sources = repo._conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        decisions = repo._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert sources == 1
        assert decisions == 1

    def test_upsert_source(self, repo: Repository, sample_source: Source):
        repo.save_source(sample_source)
        updated = Source(
            id=sample_source.id,
            source_type=sample_source.source_type,
            repo=sample_source.repo,
            url=sample_source.url,
            title="Updated title",
            raw_content="Updated content",
            fetched_at=datetime.now(),
        )
        repo.save_source(updated)
        count = repo._conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        assert count == 1
        row = repo._conn.execute(
            "SELECT title FROM sources WHERE id = ?", (sample_source.id,)
        ).fetchone()
        assert row["title"] == "Updated title"


class TestRepositoryQueries:
    def test_get_all_decisions(self, populated_repo: Repository):
        decisions = populated_repo.get_all_decisions()
        assert len(decisions) == 2

    def test_get_all_decisions_filter_by_source_type(self, populated_repo: Repository):
        pr_decisions = populated_repo.get_all_decisions(source_type="pr")
        assert len(pr_decisions) == 1
        assert pr_decisions[0]["source_type"] == "pr"

        adr_decisions = populated_repo.get_all_decisions(source_type="adr")
        assert len(adr_decisions) == 1

    def test_get_all_decisions_filter_by_repo(self, populated_repo: Repository):
        decisions = populated_repo.get_all_decisions(repo="acme/webapp")
        assert len(decisions) == 2

        decisions = populated_repo.get_all_decisions(repo="other/repo")
        assert len(decisions) == 0

    def test_get_all_decisions_limit(self, populated_repo: Repository):
        decisions = populated_repo.get_all_decisions(limit=1)
        assert len(decisions) == 1

    def test_get_decisions_by_entity(self, populated_repo: Repository):
        results = populated_repo.get_decisions_by_entity("fastapi")
        assert len(results) == 1
        assert "FastAPI" in results[0]["summary"]

    def test_get_decisions_by_entity_case_insensitive(self, populated_repo: Repository):
        results = populated_repo.get_decisions_by_entity("FastAPI")
        assert len(results) == 1

    def test_get_decisions_by_entity_no_match(self, populated_repo: Repository):
        results = populated_repo.get_decisions_by_entity("redis")
        assert len(results) == 0

    def test_search_decisions_fts(self, populated_repo: Repository):
        results = populated_repo.search_decisions("FastAPI")
        assert len(results) >= 1
        assert any("FastAPI" in d["summary"] for d in results)

    def test_search_decisions_fts_reasoning(self, populated_repo: Repository):
        results = populated_repo.search_decisions("async")
        assert len(results) >= 1

    def test_get_entities(self, populated_repo: Repository):
        entities = populated_repo.get_entities()
        entity_names = {e["entity"] for e in entities}
        assert "fastapi" in entity_names
        assert "postgresql" in entity_names

    def test_get_stats(self, populated_repo: Repository):
        stats = populated_repo.get_stats()
        assert stats["total_sources"] == 2
        assert stats["total_decisions"] == 2
        assert stats["pr_sources"] == 1
        assert stats["adr_sources"] == 1
        assert stats["doc_sources"] == 0

    def test_decision_dict_has_entities(self, populated_repo: Repository):
        decisions = populated_repo.get_all_decisions()
        for d in decisions:
            assert "entities" in d
            assert isinstance(d["entities"], list)

    def test_decision_dict_alternatives_parsed(self, populated_repo: Repository):
        decisions = populated_repo.get_all_decisions(source_type="pr")
        assert decisions[0]["alternatives"] == ["Flask", "Django REST Framework"]
