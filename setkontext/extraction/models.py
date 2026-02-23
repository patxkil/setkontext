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
    source_type: str  # "pr" | "adr" | "doc"
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
