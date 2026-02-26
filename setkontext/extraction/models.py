"""Core data models for setkontext."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Entity:
    name: str  # e.g. "postgres", "react", "monolith"
    entity_type: str  # "technology" | "pattern" | "service" | "library"


@dataclass
class Source:
    id: str  # "pr:123" or "adr:docs/adr/001.md"
    source_type: str  # "pr" | "adr" | "doc" | "session"
    repo: str  # "owner/repo"
    url: str  # GitHub permalink
    title: str
    raw_content: str  # Full text that was analyzed
    fetched_at: datetime


@dataclass
class Decision:
    id: str  # UUID
    source_id: str  # FK to Source
    summary: str  # What was decided
    reasoning: str  # Why (tradeoffs, context)
    alternatives: list[str] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    confidence: str = "medium"  # "high" | "medium" | "low"
    decision_date: str = ""  # ISO date string from PR merge or ADR
    extracted_at: datetime = field(default_factory=datetime.now)


@dataclass
class Learning:
    id: str  # UUID
    source_id: str  # FK to Source
    category: str  # "bug_fix" | "gotcha" | "implementation"
    summary: str  # One sentence: what happened
    detail: str  # Full context: root cause, fix, what to know
    components: list[str] = field(default_factory=list)  # Affected files/modules
    entities: list[Entity] = field(default_factory=list)  # Technologies involved
    session_date: str = ""  # When this happened
    extracted_at: datetime = field(default_factory=datetime.now)
