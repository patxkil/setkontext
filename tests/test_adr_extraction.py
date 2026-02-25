"""Tests for setkontext.extraction.adr — fully deterministic, no API calls."""

from __future__ import annotations

from setkontext.extraction.adr import (
    _assess_confidence,
    _build_summary,
    _extract_alternatives,
    _extract_date,
    _extract_entities_from_text,
    _extract_title,
    _parse_sections,
    extract_adr_decisions,
)
from setkontext.github.fetcher import ADRData

NYGARD_ADR = """\
# ADR-001: Use PostgreSQL for primary datastore

## Status

Accepted

## Context

We need a relational database with strong consistency, good tooling ecosystem,
and support for complex queries. The team has experience with PostgreSQL.

## Decision

We will use PostgreSQL as the primary datastore for all services.

## Consequences

- We need to manage schema migrations
- Connection pooling must be configured (pgbouncer)
- Developers need PostgreSQL installed locally

## Alternatives

- MySQL — less feature-rich, but wider hosting support
- MongoDB — document model doesn't fit our relational data
- SQLite — not suitable for multi-service production workloads
"""

MADR_ADR = """\
# Use React for Frontend

## Status

Accepted (2024-05-20)

## Context and Problem Statement

We need a frontend framework for our new dashboard application.

## Considered Options

- React with TypeScript
- Vue 3 with TypeScript
- Svelte
- Angular

## Decision Outcome

Chosen option: React with TypeScript, because the team has the most experience
with it and the ecosystem is the most mature for our needs.
"""

MINIMAL_ADR = """\
# Choose a message queue

## Context

We need async processing for email notifications.

## Decision

Use RabbitMQ for message queuing.
"""

EMPTY_ADR = """\
# Some Title

This document has no structured sections at all.
Just free-form text about architecture stuff.
"""


class TestExtractTitle:
    def test_standard_title(self):
        assert _extract_title("# Use PostgreSQL\n\nBody") == "Use PostgreSQL"

    def test_strips_adr_prefix(self):
        assert _extract_title("# ADR-001: Use Postgres\n") == "Use Postgres"

    def test_strips_numbered_prefix(self):
        assert _extract_title("# 3. Choose a database\n") == "Choose a database"

    def test_fallback_to_first_line(self):
        assert _extract_title("No heading here\nJust text") == "No heading here"

    def test_empty_content(self):
        assert _extract_title("") == "Untitled ADR"


class TestParseSections:
    def test_nygard_format(self):
        sections = _parse_sections(NYGARD_ADR)
        assert "status" in sections
        assert "context" in sections
        assert "decision" in sections
        assert "consequences" in sections
        assert "alternatives" in sections

    def test_madr_format(self):
        sections = _parse_sections(MADR_ADR)
        assert "context" in sections
        assert "decision" in sections or "alternatives" in sections

    def test_section_content(self):
        sections = _parse_sections(NYGARD_ADR)
        assert "PostgreSQL" in sections["decision"]
        assert "relational database" in sections["context"]

    def test_no_sections(self):
        sections = _parse_sections(EMPTY_ADR)
        assert sections == {}


class TestBuildSummary:
    def test_uses_decision_section(self):
        sections = {"decision": "Use PostgreSQL for everything."}
        assert _build_summary(sections, "Fallback") == "Use PostgreSQL for everything."

    def test_truncates_long_decision(self):
        sections = {"decision": "A" * 400}
        result = _build_summary(sections, "Fallback")
        assert len(result) <= 300
        assert result.endswith("...")

    def test_falls_back_to_title(self):
        sections = {"context": "Some context but no decision"}
        assert _build_summary(sections, "The Title") == "The Title"


class TestExtractAlternatives:
    def test_bullet_list(self):
        text = "- MySQL\n- MongoDB\n- SQLite"
        alts = _extract_alternatives(text)
        assert alts == ["MySQL", "MongoDB", "SQLite"]

    def test_numbered_list(self):
        text = "1. Option A\n2. Option B"
        alts = _extract_alternatives(text)
        assert alts == ["Option A", "Option B"]

    def test_asterisk_list(self):
        text = "* React\n* Vue\n* Angular"
        alts = _extract_alternatives(text)
        assert alts == ["React", "Vue", "Angular"]

    def test_empty(self):
        assert _extract_alternatives("") == []

    def test_mixed_with_descriptions(self):
        text = "- MySQL — less feature-rich\n- MongoDB — document model"
        alts = _extract_alternatives(text)
        assert len(alts) == 2


class TestExtractEntities:
    def test_finds_technologies(self):
        text = "We chose PostgreSQL over MySQL for the database."
        entities = _extract_entities_from_text(text)
        names = {e.name for e in entities}
        assert "postgresql" in names or "postgres" in names
        assert "mysql" in names

    def test_finds_patterns(self):
        text = "We adopted a microservice architecture with event-driven messaging."
        entities = _extract_entities_from_text(text)
        names = {e.name for e in entities}
        assert "microservice" in names
        assert "event-driven" in names

    def test_word_boundary_matching(self):
        """'go' should not match inside 'MongoDB'."""
        text = "We use MongoDB for storage."
        entities = _extract_entities_from_text(text)
        names = {e.name for e in entities}
        assert "mongodb" in names
        assert "go" not in names

    def test_no_entities(self):
        text = "We decided to update the README file."
        entities = _extract_entities_from_text(text)
        assert entities == []

    def test_no_duplicates(self):
        text = "PostgreSQL is great. We love PostgreSQL."
        entities = _extract_entities_from_text(text)
        pg_entities = [e for e in entities if "postgre" in e.name]
        assert len(pg_entities) <= 1


class TestAssessConfidence:
    def test_high_full(self):
        sections = {"decision": "x", "context": "y", "alternatives": "z"}
        assert _assess_confidence(sections) == "high"

    def test_high_decision_and_context(self):
        sections = {"decision": "x", "context": "y"}
        assert _assess_confidence(sections) == "high"

    def test_medium_decision_only(self):
        sections = {"decision": "x"}
        assert _assess_confidence(sections) == "medium"

    def test_medium_context_only(self):
        sections = {"context": "x"}
        assert _assess_confidence(sections) == "medium"

    def test_low_nothing(self):
        assert _assess_confidence({}) == "low"


class TestExtractDate:
    def test_iso_date(self):
        assert _extract_date("Date: 2024-03-15") == "2024-03-15"

    def test_date_in_status(self):
        assert _extract_date("Accepted (2024-05-20)") == "2024-05-20"

    def test_no_date(self):
        assert _extract_date("No date here at all") == ""


class TestExtractAdrDecisions:
    def test_nygard_adr(self):
        adr = ADRData(
            path="docs/adr/001-use-postgres.md",
            content=NYGARD_ADR,
            url="https://github.com/acme/repo/blob/main/docs/adr/001-use-postgres.md",
        )
        source, decisions = extract_adr_decisions(adr, "acme/repo")

        assert source.id == "adr:docs/adr/001-use-postgres.md"
        assert source.source_type == "adr"
        assert len(decisions) == 1

        d = decisions[0]
        assert "PostgreSQL" in d.summary
        assert d.confidence == "high"
        assert len(d.alternatives) > 0

    def test_madr_adr(self):
        adr = ADRData(path="docs/adr/002-react.md", content=MADR_ADR, url="http://x")
        source, decisions = extract_adr_decisions(adr, "acme/repo")

        assert source.source_type == "adr"
        assert len(decisions) == 1
        assert decisions[0].decision_date == "2024-05-20"

    def test_minimal_adr(self):
        adr = ADRData(path="adr/003.md", content=MINIMAL_ADR, url="http://x")
        source, decisions = extract_adr_decisions(adr, "acme/repo")
        assert len(decisions) == 1
        assert "RabbitMQ" in decisions[0].summary

    def test_empty_adr_yields_no_decisions(self):
        adr = ADRData(path="adr/empty.md", content=EMPTY_ADR, url="http://x")
        source, decisions = extract_adr_decisions(adr, "acme/repo")
        assert len(decisions) == 0
        assert source.id == "adr:adr/empty.md"
