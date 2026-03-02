"""Tests for entity relationship CRUD and graph queries."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from setkontext.extraction.models import (
    Decision,
    Entity,
    EntityRelationship,
    Learning,
    Source,
)
from setkontext.storage.repository import Repository


class TestSaveEntityRelationship:
    def test_save_and_retrieve(self, repo: Repository, sample_source: Source):
        repo.save_source(sample_source)
        rel = EntityRelationship(
            from_entity="fastapi",
            to_entity="pydantic",
            relationship="uses",
            source_id=sample_source.id,
        )
        repo.save_entity_relationship(rel)
        related = repo.get_related_entities("fastapi")
        assert len(related) == 1
        assert related[0]["entity"] == "pydantic"
        assert related[0]["relationship"] == "uses"

    def test_save_batch(self, repo: Repository, sample_source: Source):
        repo.save_source(sample_source)
        rels = [
            EntityRelationship("fastapi", "pydantic", "uses", sample_source.id),
            EntityRelationship("fastapi", "uvicorn", "depends_on", sample_source.id),
            EntityRelationship("postgresql", "mongodb", "replaces", sample_source.id),
        ]
        repo.save_entity_relationships(rels)
        related = repo.get_related_entities("fastapi")
        assert len(related) == 2
        related_names = {r["entity"] for r in related}
        assert "pydantic" in related_names
        assert "uvicorn" in related_names

    def test_case_insensitive(self, repo: Repository, sample_source: Source):
        repo.save_source(sample_source)
        rel = EntityRelationship("FastAPI", "Pydantic", "uses", sample_source.id)
        repo.save_entity_relationship(rel)
        # Query with lowercase
        related = repo.get_related_entities("fastapi")
        assert len(related) == 1

    def test_duplicate_ignored(self, repo: Repository, sample_source: Source):
        repo.save_source(sample_source)
        rel = EntityRelationship("fastapi", "pydantic", "uses", sample_source.id)
        repo.save_entity_relationship(rel)
        repo.save_entity_relationship(rel)  # duplicate
        related = repo.get_related_entities("fastapi")
        assert len(related) == 1


class TestGetRelatedEntities:
    def test_bidirectional(self, repo: Repository, sample_source: Source):
        """Relationships should be found from either direction."""
        repo.save_source(sample_source)
        rel = EntityRelationship("fastapi", "pydantic", "uses", sample_source.id)
        repo.save_entity_relationship(rel)
        # Query from the "to" side
        related = repo.get_related_entities("pydantic")
        assert len(related) == 1
        assert related[0]["entity"] == "fastapi"

    def test_depth_two(self, repo: Repository, sample_source: Source):
        """Should traverse 2 hops when depth=2."""
        repo.save_source(sample_source)
        rels = [
            EntityRelationship("fastapi", "pydantic", "uses", sample_source.id),
            EntityRelationship("pydantic", "python", "depends_on", sample_source.id),
        ]
        repo.save_entity_relationships(rels)
        # Depth 1: only pydantic
        related_1 = repo.get_related_entities("fastapi", depth=1)
        assert len(related_1) == 1
        # Depth 2: pydantic + python
        related_2 = repo.get_related_entities("fastapi", depth=2)
        assert len(related_2) == 2

    def test_no_relationships(self, repo: Repository):
        related = repo.get_related_entities("nonexistent")
        assert related == []


class TestGetEntityGraph:
    def test_returns_nodes_and_edges(
        self, repo: Repository, sample_source: Source, sample_decision: Decision,
    ):
        repo.save_extraction_result(sample_source, [sample_decision])
        rel = EntityRelationship("fastapi", "flask", "replaces", sample_source.id)
        repo.save_entity_relationship(rel)

        graph = repo.get_entity_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) >= 2  # fastapi and flask
        assert len(graph["edges"]) == 1

    def test_empty_graph(self, repo: Repository):
        graph = repo.get_entity_graph()
        assert graph["nodes"] == []
        assert graph["edges"] == []
