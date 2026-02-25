"""Tests for setkontext.extraction.models."""

from __future__ import annotations

from datetime import datetime

from setkontext.extraction.models import Decision, Entity, Source


class TestEntity:
    def test_create(self):
        e = Entity(name="fastapi", entity_type="technology")
        assert e.name == "fastapi"
        assert e.entity_type == "technology"


class TestSource:
    def test_create(self):
        s = Source(
            id="pr:1",
            source_type="pr",
            repo="acme/webapp",
            url="https://github.com/acme/webapp/pull/1",
            title="Initial PR",
            raw_content="content",
            fetched_at=datetime(2024, 1, 1),
        )
        assert s.id == "pr:1"
        assert s.source_type == "pr"

    def test_source_types(self):
        for stype in ("pr", "adr", "doc", "session"):
            s = Source(
                id=f"{stype}:1",
                source_type=stype,
                repo="r",
                url="u",
                title="t",
                raw_content="c",
                fetched_at=datetime.now(),
            )
            assert s.source_type == stype


class TestDecision:
    def test_defaults(self):
        d = Decision(
            id="abc",
            source_id="pr:1",
            summary="Use X",
            reasoning="Because Y",
        )
        assert d.alternatives == []
        assert d.entities == []
        assert d.confidence == "medium"
        assert d.decision_date == ""

    def test_full_decision(self):
        d = Decision(
            id="abc",
            source_id="pr:1",
            summary="Chose PostgreSQL",
            reasoning="Need ACID compliance",
            alternatives=["MySQL", "MongoDB"],
            entities=[Entity(name="postgresql", entity_type="technology")],
            confidence="high",
            decision_date="2024-03-01",
        )
        assert len(d.alternatives) == 2
        assert d.entities[0].name == "postgresql"
        assert d.confidence == "high"
