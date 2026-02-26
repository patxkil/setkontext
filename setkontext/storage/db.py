"""SQLite database setup and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    repo TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    raw_content TEXT,
    fetched_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    summary TEXT NOT NULL,
    reasoning TEXT,
    alternatives TEXT,
    confidence TEXT,
    decision_date TEXT,
    extracted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decision_entities (
    decision_id TEXT NOT NULL REFERENCES decisions(id),
    entity TEXT NOT NULL,
    entity_type TEXT,
    PRIMARY KEY (decision_id, entity)
);

CREATE TABLE IF NOT EXISTS learnings (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT,
    components TEXT,
    session_date TEXT,
    extracted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learning_entities (
    learning_id TEXT NOT NULL REFERENCES learnings(id),
    entity TEXT NOT NULL,
    entity_type TEXT,
    PRIMARY KEY (learning_id, entity)
);

CREATE INDEX IF NOT EXISTS idx_decisions_source ON decisions(source_id);
CREATE INDEX IF NOT EXISTS idx_entities_entity ON decision_entities(entity);
CREATE INDEX IF NOT EXISTS idx_sources_repo ON sources(repo);
CREATE INDEX IF NOT EXISTS idx_learnings_source ON learnings(source_id);
CREATE INDEX IF NOT EXISTS idx_learnings_category ON learnings(category);
CREATE INDEX IF NOT EXISTS idx_learning_entities_entity ON learning_entities(entity);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    summary,
    reasoning,
    alternatives,
    content='decisions',
    content_rowid='rowid'
);

-- Triggers to keep FTS index in sync
CREATE TRIGGER IF NOT EXISTS decisions_ai AFTER INSERT ON decisions BEGIN
    INSERT INTO decisions_fts(rowid, summary, reasoning, alternatives)
    VALUES (new.rowid, new.summary, new.reasoning, new.alternatives);
END;

CREATE TRIGGER IF NOT EXISTS decisions_ad AFTER DELETE ON decisions BEGIN
    INSERT INTO decisions_fts(decisions_fts, rowid, summary, reasoning, alternatives)
    VALUES ('delete', old.rowid, old.summary, old.reasoning, old.alternatives);
END;

CREATE TRIGGER IF NOT EXISTS decisions_au AFTER UPDATE ON decisions BEGIN
    INSERT INTO decisions_fts(decisions_fts, rowid, summary, reasoning, alternatives)
    VALUES ('delete', old.rowid, old.summary, old.reasoning, old.alternatives);
    INSERT INTO decisions_fts(rowid, summary, reasoning, alternatives)
    VALUES (new.rowid, new.summary, new.reasoning, new.alternatives);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
    summary,
    detail,
    components,
    content='learnings',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS learnings_ai AFTER INSERT ON learnings BEGIN
    INSERT INTO learnings_fts(rowid, summary, detail, components)
    VALUES (new.rowid, new.summary, new.detail, new.components);
END;

CREATE TRIGGER IF NOT EXISTS learnings_ad AFTER DELETE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, rowid, summary, detail, components)
    VALUES ('delete', old.rowid, old.summary, old.detail, old.components);
END;

CREATE TRIGGER IF NOT EXISTS learnings_au AFTER UPDATE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, rowid, summary, detail, components)
    VALUES ('delete', old.rowid, old.summary, old.detail, old.components);
    INSERT INTO learnings_fts(rowid, summary, detail, components)
    VALUES (new.rowid, new.summary, new.detail, new.components);
END;
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Create or open a SQLite database with the setkontext schema."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_SQL)
    conn.commit()

    return conn
