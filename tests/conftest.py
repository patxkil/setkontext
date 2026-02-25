"""Shared test fixtures for setkontext."""

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


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def db_conn(db_path: Path) -> sqlite3.Connection:
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def repo(db_conn: sqlite3.Connection) -> Repository:
    return Repository(db_conn)


@pytest.fixture
def sample_source() -> Source:
    return Source(
        id="pr:42",
        source_type="pr",
        repo="acme/webapp",
        url="https://github.com/acme/webapp/pull/42",
        title="Migrate to FastAPI",
        raw_content="We chose FastAPI over Flask for the new API layer.",
        fetched_at=datetime(2024, 6, 15, 10, 0, 0),
    )


@pytest.fixture
def sample_decision(sample_source: Source) -> Decision:
    return Decision(
        id=str(uuid.uuid4()),
        source_id=sample_source.id,
        summary="Adopted FastAPI as the web framework for all new API endpoints",
        reasoning="FastAPI provides async support, automatic OpenAPI docs, and Pydantic validation. Flask lacks native async.",
        alternatives=["Flask", "Django REST Framework"],
        entities=[
            Entity(name="fastapi", entity_type="technology"),
            Entity(name="flask", entity_type="technology"),
        ],
        confidence="high",
        decision_date="2024-06-15",
        extracted_at=datetime(2024, 6, 15, 12, 0, 0),
    )


@pytest.fixture
def sample_adr_decision() -> tuple[Source, Decision]:
    source = Source(
        id="adr:docs/adr/001-use-postgres.md",
        source_type="adr",
        repo="acme/webapp",
        url="https://github.com/acme/webapp/blob/main/docs/adr/001-use-postgres.md",
        title="Use PostgreSQL for primary datastore",
        raw_content="# ADR-001: Use PostgreSQL\n\n## Status\nAccepted\n\n## Context\nWe need a relational database.\n\n## Decision\nUse PostgreSQL.\n\n## Consequences\nNeed to manage migrations.",
        fetched_at=datetime(2024, 3, 1),
    )
    decision = Decision(
        id=str(uuid.uuid4()),
        source_id=source.id,
        summary="Use PostgreSQL as the primary datastore",
        reasoning="We need a relational database with strong consistency guarantees.",
        alternatives=["MySQL", "SQLite"],
        entities=[Entity(name="postgresql", entity_type="technology")],
        confidence="high",
        decision_date="2024-03-01",
        extracted_at=datetime(2024, 3, 1, 12, 0, 0),
    )
    return source, decision


@pytest.fixture
def populated_repo(
    repo: Repository,
    sample_source: Source,
    sample_decision: Decision,
    sample_adr_decision: tuple[Source, Decision],
) -> Repository:
    """Repository pre-loaded with sample data for query/search tests."""
    repo.save_extraction_result(sample_source, [sample_decision])
    adr_source, adr_decision = sample_adr_decision
    repo.save_extraction_result(adr_source, [adr_decision])
    return repo
