"""CRUD operations for decisions and sources."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from setkontext.extraction.models import Decision, Entity, Source


class Repository:
    """Data access layer for the setkontext SQLite database."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_source(self, source: Source) -> None:
        """Insert or replace a source record."""
        self._conn.execute(
            """INSERT OR REPLACE INTO sources (id, source_type, repo, url, title, raw_content, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                source.id,
                source.source_type,
                source.repo,
                source.url,
                source.title,
                source.raw_content,
                source.fetched_at.isoformat(),
            ),
        )
        self._conn.commit()

    def save_decision(self, decision: Decision) -> None:
        """Insert or replace a decision and its entities."""
        self._conn.execute(
            """INSERT OR REPLACE INTO decisions
            (id, source_id, summary, reasoning, alternatives, confidence, decision_date, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision.id,
                decision.source_id,
                decision.summary,
                decision.reasoning,
                json.dumps(decision.alternatives),
                decision.confidence,
                decision.decision_date,
                decision.extracted_at.isoformat(),
            ),
        )

        # Clear existing entities for this decision (in case of re-extraction)
        self._conn.execute(
            "DELETE FROM decision_entities WHERE decision_id = ?", (decision.id,)
        )

        # Insert entities
        for entity in decision.entities:
            self._conn.execute(
                """INSERT OR IGNORE INTO decision_entities (decision_id, entity, entity_type)
                VALUES (?, ?, ?)""",
                (decision.id, entity.name, entity.entity_type),
            )

        self._conn.commit()

    def save_extraction_result(self, source: Source, decisions: list[Decision]) -> None:
        """Save a source and all its extracted decisions in one transaction."""
        self.save_source(source)
        for decision in decisions:
            self.save_decision(decision)

    def get_all_decisions(
        self,
        repo: str | None = None,
        source_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get decisions with optional filters. Returns dicts for easy serialization."""
        query = """
            SELECT d.*, s.url as source_url, s.title as source_title, s.source_type
            FROM decisions d
            JOIN sources s ON d.source_id = s.id
            WHERE 1=1
        """
        params: list = []

        if repo:
            query += " AND s.repo = ?"
            params.append(repo)
        if source_type:
            query += " AND s.source_type = ?"
            params.append(source_type)

        query += " ORDER BY d.extracted_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_decision_dict(row) for row in rows]

    def get_decisions_by_entity(self, entity: str) -> list[dict]:
        """Find all decisions related to a specific entity."""
        rows = self._conn.execute(
            """
            SELECT d.*, s.url as source_url, s.title as source_title, s.source_type
            FROM decisions d
            JOIN sources s ON d.source_id = s.id
            JOIN decision_entities de ON d.id = de.decision_id
            WHERE LOWER(de.entity) = LOWER(?)
            ORDER BY d.extracted_at DESC
            """,
            (entity,),
        ).fetchall()
        return [self._row_to_decision_dict(row) for row in rows]

    def search_decisions(self, query_text: str, limit: int = 20) -> list[dict]:
        """Full-text search across decision summaries, reasoning, and alternatives."""
        rows = self._conn.execute(
            """
            SELECT d.*, s.url as source_url, s.title as source_title, s.source_type
            FROM decisions d
            JOIN sources s ON d.source_id = s.id
            JOIN decisions_fts fts ON d.rowid = fts.rowid
            WHERE decisions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query_text, limit),
        ).fetchall()
        return [self._row_to_decision_dict(row) for row in rows]

    def get_entities(self) -> list[dict]:
        """Get all unique entities with their decision counts."""
        rows = self._conn.execute(
            """
            SELECT entity, entity_type, COUNT(*) as decision_count
            FROM decision_entities
            GROUP BY entity, entity_type
            ORDER BY decision_count DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self) -> dict:
        """Get summary statistics about the extracted data."""
        sources_count = self._conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        decisions_count = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        entities_count = self._conn.execute(
            "SELECT COUNT(DISTINCT entity) FROM decision_entities"
        ).fetchone()[0]
        pr_sources = self._conn.execute(
            "SELECT COUNT(*) FROM sources WHERE source_type = 'pr'"
        ).fetchone()[0]
        adr_sources = self._conn.execute(
            "SELECT COUNT(*) FROM sources WHERE source_type = 'adr'"
        ).fetchone()[0]
        doc_sources = self._conn.execute(
            "SELECT COUNT(*) FROM sources WHERE source_type = 'doc'"
        ).fetchone()[0]
        session_sources = self._conn.execute(
            "SELECT COUNT(*) FROM sources WHERE source_type = 'session'"
        ).fetchone()[0]

        return {
            "total_sources": sources_count,
            "total_decisions": decisions_count,
            "unique_entities": entities_count,
            "pr_sources": pr_sources,
            "adr_sources": adr_sources,
            "doc_sources": doc_sources,
            "session_sources": session_sources,
        }

    def _row_to_decision_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a decision dict with entities."""
        d = dict(row)
        # Parse alternatives JSON
        if d.get("alternatives"):
            try:
                d["alternatives"] = json.loads(d["alternatives"])
            except json.JSONDecodeError:
                d["alternatives"] = []
        else:
            d["alternatives"] = []

        # Fetch entities for this decision
        entity_rows = self._conn.execute(
            "SELECT entity, entity_type FROM decision_entities WHERE decision_id = ?",
            (d["id"],),
        ).fetchall()
        d["entities"] = [dict(r) for r in entity_rows]

        return d
