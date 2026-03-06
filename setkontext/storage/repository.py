"""CRUD operations for decisions and sources."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from setkontext.extraction.models import (
    Decision,
    Entity,
    EntityRelationship,
    Learning,
    Source,
)


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

    # ── Learning CRUD ──────────────────────────────────────────────

    def save_learning(self, learning: Learning) -> None:
        """Insert or replace a learning and its entities."""
        self._conn.execute(
            """INSERT OR REPLACE INTO learnings
            (id, source_id, category, summary, detail, components, session_date, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                learning.id,
                learning.source_id,
                learning.category,
                learning.summary,
                learning.detail,
                json.dumps(learning.components),
                learning.session_date,
                learning.extracted_at.isoformat(),
            ),
        )

        self._conn.execute(
            "DELETE FROM learning_entities WHERE learning_id = ?", (learning.id,)
        )

        for entity in learning.entities:
            self._conn.execute(
                """INSERT OR IGNORE INTO learning_entities (learning_id, entity, entity_type)
                VALUES (?, ?, ?)""",
                (learning.id, entity.name, entity.entity_type),
            )

        # Save file references from components
        if learning.components:
            for path in learning.components:
                if path:
                    self._conn.execute(
                        """INSERT OR IGNORE INTO file_references (item_type, item_id, file_path)
                        VALUES (?, ?, ?)""",
                        ("learning", learning.id, path),
                    )

        self._conn.commit()

    def save_learning_result(self, source: Source, learnings: list[Learning]) -> None:
        """Save a source and all its extracted learnings in one transaction."""
        self.save_source(source)
        for learning in learnings:
            self.save_learning(learning)

    def search_learnings(
        self, query_text: str, category: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Full-text search across learning summaries, details, and components."""
        if category:
            rows = self._conn.execute(
                """
                SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
                FROM learnings l
                JOIN sources s ON l.source_id = s.id
                JOIN learnings_fts fts ON l.rowid = fts.rowid
                WHERE learnings_fts MATCH ? AND l.category = ?
                ORDER BY rank
                LIMIT ?
                """,
                (query_text, category, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
                FROM learnings l
                JOIN sources s ON l.source_id = s.id
                JOIN learnings_fts fts ON l.rowid = fts.rowid
                WHERE learnings_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query_text, limit),
            ).fetchall()
        return [self._row_to_learning_dict(row) for row in rows]

    def get_recent_learnings(
        self, limit: int = 20, category: str | None = None
    ) -> list[dict]:
        """Get most recent learnings, optionally filtered by category."""
        if category:
            rows = self._conn.execute(
                """
                SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
                FROM learnings l
                JOIN sources s ON l.source_id = s.id
                WHERE l.category = ?
                ORDER BY l.extracted_at DESC
                LIMIT ?
                """,
                (category, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
                FROM learnings l
                JOIN sources s ON l.source_id = s.id
                ORDER BY l.extracted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_learning_dict(row) for row in rows]

    def get_learnings_by_entity(self, entity: str) -> list[dict]:
        """Find all learnings related to a specific entity."""
        rows = self._conn.execute(
            """
            SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
            FROM learnings l
            JOIN sources s ON l.source_id = s.id
            JOIN learning_entities le ON l.id = le.learning_id
            WHERE LOWER(le.entity) = LOWER(?)
            ORDER BY l.extracted_at DESC
            """,
            (entity,),
        ).fetchall()
        return [self._row_to_learning_dict(row) for row in rows]

    def get_learning_stats(self) -> dict:
        """Get learning counts by category."""
        total = self._conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
        bug_fixes = self._conn.execute(
            "SELECT COUNT(*) FROM learnings WHERE category = 'bug_fix'"
        ).fetchone()[0]
        gotchas = self._conn.execute(
            "SELECT COUNT(*) FROM learnings WHERE category = 'gotcha'"
        ).fetchone()[0]
        implementations = self._conn.execute(
            "SELECT COUNT(*) FROM learnings WHERE category = 'implementation'"
        ).fetchone()[0]
        return {
            "total_learnings": total,
            "bug_fixes": bug_fixes,
            "gotchas": gotchas,
            "implementations": implementations,
        }

    # ── Consolidation Queries ─────────────────────────────────────

    def get_learning_clusters(self, min_count: int = 2) -> list[dict]:
        """Find entities that appear in multiple learnings — candidates for consolidation.

        Returns groups of learnings sharing the same entity, sorted by count descending.
        Only includes entities with at least `min_count` learnings.
        """
        rows = self._conn.execute(
            """
            SELECT le.entity, le.entity_type, COUNT(DISTINCT le.learning_id) as learning_count
            FROM learning_entities le
            JOIN learnings l ON le.learning_id = l.id
            GROUP BY le.entity, le.entity_type
            HAVING COUNT(DISTINCT le.learning_id) >= ?
            ORDER BY learning_count DESC
            """,
            (min_count,),
        ).fetchall()

        clusters: list[dict] = []
        for row in rows:
            entity = row["entity"]
            learnings = self.get_learnings_by_entity(entity)

            # Check if this entity already has decisions (may not need consolidation)
            existing_decisions = self.get_decisions_by_entity(entity)

            clusters.append({
                "entity": entity,
                "entity_type": row["entity_type"],
                "learning_count": row["learning_count"],
                "existing_decision_count": len(existing_decisions),
                "learnings": learnings,
            })

        return clusters

    def get_unconsolidated_learnings(self, limit: int = 50) -> list[dict]:
        """Get learnings from source_type='learning' (session captures) that
        haven't been consolidated into decisions yet.

        A learning is considered unconsolidated if no decision references
        its source_id as a consolidation origin.
        """
        rows = self._conn.execute(
            """
            SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
            FROM learnings l
            JOIN sources s ON l.source_id = s.id
            WHERE s.source_type = 'learning'
            AND l.source_id NOT IN (
                SELECT DISTINCT s2.id FROM sources s2
                WHERE s2.source_type = 'consolidation'
            )
            ORDER BY l.extracted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_learning_dict(row) for row in rows]

    # ── Entity Relationships ────────────────────────────────────────

    def save_entity_relationship(self, rel: EntityRelationship) -> None:
        """Insert or ignore an entity relationship."""
        self._conn.execute(
            """INSERT OR IGNORE INTO entity_relationships
            (from_entity, to_entity, relationship, source_id, confidence)
            VALUES (?, ?, ?, ?, ?)""",
            (
                rel.from_entity.lower(),
                rel.to_entity.lower(),
                rel.relationship,
                rel.source_id,
                rel.confidence,
            ),
        )
        self._conn.commit()

    def save_entity_relationships(self, rels: list[EntityRelationship]) -> None:
        """Batch save entity relationships."""
        for rel in rels:
            self._conn.execute(
                """INSERT OR IGNORE INTO entity_relationships
                (from_entity, to_entity, relationship, source_id, confidence)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    rel.from_entity.lower(),
                    rel.to_entity.lower(),
                    rel.relationship,
                    rel.source_id,
                    rel.confidence,
                ),
            )
        self._conn.commit()

    def get_related_entities(self, entity: str, depth: int = 1) -> list[dict]:
        """Get entities related to the given entity, traversing up to depth hops."""
        entity_lower = entity.lower()
        visited: set[str] = {entity_lower}
        results: list[dict] = []

        current_entities = {entity_lower}
        for _hop in range(depth):
            if not current_entities:
                break
            placeholders = ",".join("?" for _ in current_entities)
            rows = self._conn.execute(
                f"""
                SELECT from_entity, to_entity, relationship, confidence
                FROM entity_relationships
                WHERE LOWER(from_entity) IN ({placeholders})
                   OR LOWER(to_entity) IN ({placeholders})
                """,
                list(current_entities) + list(current_entities),
            ).fetchall()

            next_entities: set[str] = set()
            for row in rows:
                r = dict(row)
                other = r["to_entity"] if r["from_entity"] in visited else r["from_entity"]
                if other not in visited:
                    results.append({
                        "entity": other,
                        "relationship": r["relationship"],
                        "confidence": r["confidence"],
                        "via": r["from_entity"] if other == r["to_entity"] else r["to_entity"],
                    })
                    next_entities.add(other)
            visited.update(next_entities)
            current_entities = next_entities

        return results

    def get_entity_graph(self) -> dict:
        """Get the full entity graph for visualization."""
        # Build nodes from both decision and learning entities
        entity_rows = self._conn.execute(
            """
            SELECT entity, entity_type, COUNT(*) as decision_count
            FROM decision_entities
            GROUP BY entity, entity_type
            """
        ).fetchall()

        learning_counts = {}
        for row in self._conn.execute(
            "SELECT entity, COUNT(*) as cnt FROM learning_entities GROUP BY entity"
        ).fetchall():
            learning_counts[row["entity"].lower()] = row["cnt"]

        nodes = []
        seen_entities: set[str] = set()
        for row in entity_rows:
            entity_lower = row["entity"].lower()
            if entity_lower not in seen_entities:
                seen_entities.add(entity_lower)
                nodes.append({
                    "entity": row["entity"],
                    "entity_type": row["entity_type"],
                    "decision_count": row["decision_count"],
                    "learning_count": learning_counts.get(entity_lower, 0),
                })

        # Add entities that only appear in learnings
        for row in self._conn.execute(
            "SELECT DISTINCT entity, entity_type FROM learning_entities"
        ).fetchall():
            if row["entity"].lower() not in seen_entities:
                seen_entities.add(row["entity"].lower())
                nodes.append({
                    "entity": row["entity"],
                    "entity_type": row["entity_type"],
                    "decision_count": 0,
                    "learning_count": learning_counts.get(row["entity"].lower(), 0),
                })

        # Build edges
        edge_rows = self._conn.execute(
            "SELECT from_entity, to_entity, relationship, confidence FROM entity_relationships"
        ).fetchall()
        edges = [dict(r) for r in edge_rows]

        return {"nodes": nodes, "edges": edges}

    # ── File References ────────────────────────────────────────────

    def save_file_references(
        self, item_type: str, item_id: str, paths: list[str]
    ) -> None:
        """Save file path references for a decision or learning."""
        for path in paths:
            if path:
                self._conn.execute(
                    """INSERT OR IGNORE INTO file_references (item_type, item_id, file_path)
                    VALUES (?, ?, ?)""",
                    (item_type, item_id, path),
                )
        self._conn.commit()

    def get_items_by_file(self, file_path: str) -> list[dict]:
        """Find decisions and learnings related to a file path (prefix match)."""
        rows = self._conn.execute(
            """
            SELECT item_type, item_id, file_path
            FROM file_references
            WHERE file_path LIKE ? OR ? LIKE file_path || '%'
            """,
            (file_path + "%", file_path),
        ).fetchall()

        results: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            key = f"{row['item_type']}:{row['item_id']}"
            if key in seen:
                continue
            seen.add(key)

            if row["item_type"] == "decision":
                d_rows = self._conn.execute(
                    """
                    SELECT d.*, s.url as source_url, s.title as source_title, s.source_type
                    FROM decisions d JOIN sources s ON d.source_id = s.id
                    WHERE d.id = ?
                    """,
                    (row["item_id"],),
                ).fetchall()
                for d in d_rows:
                    item = self._row_to_decision_dict(d)
                    item["_type"] = "decision"
                    item["_matched_file"] = row["file_path"]
                    results.append(item)
            elif row["item_type"] == "learning":
                l_rows = self._conn.execute(
                    """
                    SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
                    FROM learnings l JOIN sources s ON l.source_id = s.id
                    WHERE l.id = ?
                    """,
                    (row["item_id"],),
                ).fetchall()
                for l in l_rows:
                    item = self._row_to_learning_dict(l)
                    item["_type"] = "learning"
                    item["_matched_file"] = row["file_path"]
                    results.append(item)

        return results

    # ── Temporal Queries ───────────────────────────────────────────

    def get_decisions_in_range(
        self, start: str, end: str, limit: int = 50
    ) -> list[dict]:
        """Get decisions within a date range (inclusive)."""
        rows = self._conn.execute(
            """
            SELECT d.*, s.url as source_url, s.title as source_title, s.source_type
            FROM decisions d
            JOIN sources s ON d.source_id = s.id
            WHERE d.decision_date >= ? AND d.decision_date <= ?
            ORDER BY d.decision_date DESC
            LIMIT ?
            """,
            (start, end, limit),
        ).fetchall()
        return [self._row_to_decision_dict(row) for row in rows]

    def get_learnings_in_range(
        self, start: str, end: str, limit: int = 50
    ) -> list[dict]:
        """Get learnings within a date range (inclusive)."""
        rows = self._conn.execute(
            """
            SELECT l.*, s.url as source_url, s.title as source_title, s.source_type
            FROM learnings l
            JOIN sources s ON l.source_id = s.id
            WHERE l.session_date >= ? AND l.session_date <= ?
            ORDER BY l.session_date DESC
            LIMIT ?
            """,
            (start, end, limit),
        ).fetchall()
        return [self._row_to_learning_dict(row) for row in rows]

    def get_timeline(self, limit: int = 50) -> list[dict]:
        """Get decisions and learnings merged chronologically."""
        decisions = self._conn.execute(
            """
            SELECT d.*, s.url as source_url, s.title as source_title, s.source_type,
                   d.decision_date as item_date
            FROM decisions d
            JOIN sources s ON d.source_id = s.id
            WHERE d.decision_date != '' AND d.decision_date IS NOT NULL
            ORDER BY d.decision_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        learnings = self._conn.execute(
            """
            SELECT l.*, s.url as source_url, s.title as source_title, s.source_type,
                   l.session_date as item_date
            FROM learnings l
            JOIN sources s ON l.source_id = s.id
            WHERE l.session_date != '' AND l.session_date IS NOT NULL
            ORDER BY l.session_date DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        items: list[dict] = []
        for row in decisions:
            item = self._row_to_decision_dict(row)
            item["_type"] = "decision"
            item["_date"] = row["item_date"]
            items.append(item)
        for row in learnings:
            item = self._row_to_learning_dict(row)
            item["_type"] = "learning"
            item["_date"] = row["item_date"]
            items.append(item)

        items.sort(key=lambda x: x.get("_date", ""), reverse=True)
        return items[:limit]

    def _row_to_learning_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a learning dict with entities."""
        d = dict(row)
        if d.get("components"):
            try:
                d["components"] = json.loads(d["components"])
            except json.JSONDecodeError:
                d["components"] = []
        else:
            d["components"] = []

        entity_rows = self._conn.execute(
            "SELECT entity, entity_type FROM learning_entities WHERE learning_id = ?",
            (d["id"],),
        ).fetchall()
        d["entities"] = [dict(r) for r in entity_rows]

        return d

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

        learning_stats = self.get_learning_stats()

        return {
            "total_sources": sources_count,
            "total_decisions": decisions_count,
            "unique_entities": entities_count,
            "pr_sources": pr_sources,
            "adr_sources": adr_sources,
            "doc_sources": doc_sources,
            "session_sources": session_sources,
            **learning_stats,
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
