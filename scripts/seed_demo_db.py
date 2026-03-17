"""Seed a demo database with realistic decisions and learnings.

Usage:
    uv run python scripts/seed_demo_db.py [output_path]

Creates a pre-populated setkontext.db that can be used for demos
without needing API keys or a real GitHub repository.

The demo data is based on a fictional "acme/backend" project that
uses FastAPI, PostgreSQL, Redis, and other common technologies.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
import sys

from setkontext.storage.db import get_connection

DEMO_REPO = "acme/backend"

SOURCES = [
    {
        "id": "adr:docs/adr/001-use-postgresql.md",
        "source_type": "adr",
        "repo": DEMO_REPO,
        "url": "https://github.com/acme/backend/blob/main/docs/adr/001-use-postgresql.md",
        "title": "ADR-001: Use PostgreSQL as primary database",
        "raw_content": "# Use PostgreSQL as primary database\n\nStatus: Accepted\nDate: 2024-09-15\n\n## Context\nWe need a relational database that supports JSONB, full-text search, and strong consistency.\n\n## Decision\nUse PostgreSQL 16.\n\n## Consequences\nGood: Mature ecosystem, excellent JSON support, strong community.\nBad: More operational overhead than SQLite for small deployments.",
    },
    {
        "id": "adr:docs/adr/002-fastapi-framework.md",
        "source_type": "adr",
        "repo": DEMO_REPO,
        "url": "https://github.com/acme/backend/blob/main/docs/adr/002-fastapi-framework.md",
        "title": "ADR-002: Use FastAPI as web framework",
        "raw_content": "# Use FastAPI\n\nStatus: Accepted\nDate: 2024-09-20\n\n## Context\nNeed async-first Python framework with auto-generated OpenAPI docs.\n\n## Decision\nUse FastAPI with Pydantic v2.\n\n## Consequences\nGood: Excellent performance, auto docs, type safety.\nBad: Smaller ecosystem than Django.",
    },
    {
        "id": "adr:docs/adr/003-redis-caching.md",
        "source_type": "adr",
        "repo": DEMO_REPO,
        "url": "https://github.com/acme/backend/blob/main/docs/adr/003-redis-caching.md",
        "title": "ADR-003: Use Redis for caching and rate limiting",
        "raw_content": "# Use Redis for caching\n\nStatus: Accepted\nDate: 2024-10-05",
    },
    {
        "id": "pr:42",
        "source_type": "pr",
        "repo": DEMO_REPO,
        "url": "https://github.com/acme/backend/pull/42",
        "title": "Migrate from REST to GraphQL for mobile clients",
        "raw_content": "This PR adds a GraphQL layer (Strawberry) alongside our existing REST API...",
    },
    {
        "id": "pr:87",
        "source_type": "pr",
        "repo": DEMO_REPO,
        "url": "https://github.com/acme/backend/pull/87",
        "title": "Switch from Celery to ARQ for background jobs",
        "raw_content": "Celery was overkill for our workload. ARQ is lighter, async-native, and uses Redis which we already run.",
    },
    {
        "id": "pr:103",
        "source_type": "pr",
        "repo": DEMO_REPO,
        "url": "https://github.com/acme/backend/pull/103",
        "title": "Add structured logging with structlog",
        "raw_content": "Replaced stdlib logging with structlog for JSON-formatted, context-rich logs.",
    },
    {
        "id": "doc:docs/architecture.md",
        "source_type": "doc",
        "repo": DEMO_REPO,
        "url": "https://github.com/acme/backend/blob/main/docs/architecture.md",
        "title": "Architecture Overview",
        "raw_content": "Our backend follows a layered architecture: routers → services → repositories → database.",
    },
    {
        "id": "session:2024-12-01-auth-bug",
        "source_type": "session",
        "repo": DEMO_REPO,
        "url": "",
        "title": "Session: Fixed JWT refresh race condition",
        "raw_content": "Debugging session transcript...",
    },
    {
        "id": "session:2024-12-05-deploy",
        "source_type": "session",
        "repo": DEMO_REPO,
        "url": "",
        "title": "Session: Deployment pipeline fix",
        "raw_content": "Fixed Docker build caching issue...",
    },
    {
        "id": "session:2024-12-10-redis",
        "source_type": "session",
        "repo": DEMO_REPO,
        "url": "",
        "title": "Session: Redis connection pool tuning",
        "raw_content": "Discovered Redis connection exhaustion under load...",
    },
]

DECISIONS = [
    {
        "id": str(uuid.uuid4()),
        "source_id": "adr:docs/adr/001-use-postgresql.md",
        "summary": "Use PostgreSQL 16 as the primary relational database",
        "reasoning": "We need JSONB support for flexible metadata, full-text search for content queries, and strong ACID consistency. PostgreSQL has the most mature ecosystem for these requirements. MySQL was considered but lacks native JSONB. SQLite was too limited for concurrent writes in production.",
        "alternatives": "MySQL, SQLite, CockroachDB",
        "confidence": "high",
        "decision_date": "2024-09-15",
        "entities": [
            ("PostgreSQL", "technology"),
            ("MySQL", "technology"),
            ("SQLite", "technology"),
        ],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "adr:docs/adr/002-fastapi-framework.md",
        "summary": "Use FastAPI with Pydantic v2 as the web framework",
        "reasoning": "FastAPI is async-first, auto-generates OpenAPI docs, and has excellent type safety through Pydantic. Django was considered but its sync-first design would require workarounds for our async database access patterns. Flask was too minimal — we'd have to build too much from scratch.",
        "alternatives": "Django, Flask, Litestar",
        "confidence": "high",
        "decision_date": "2024-09-20",
        "entities": [
            ("FastAPI", "technology"),
            ("Pydantic", "library"),
            ("Django", "technology"),
        ],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "adr:docs/adr/003-redis-caching.md",
        "summary": "Use Redis for application caching and rate limiting",
        "reasoning": "Redis provides sub-millisecond reads, built-in TTL expiration, and rate limiting primitives. We already use it for our background job queue (ARQ), so adding caching avoids introducing another infrastructure dependency. Memcached was considered but lacks persistence and pub/sub which we plan to use for cache invalidation.",
        "alternatives": "Memcached, in-process caching, DynamoDB DAX",
        "confidence": "high",
        "decision_date": "2024-10-05",
        "entities": [
            ("Redis", "technology"),
            ("Memcached", "technology"),
            ("ARQ", "library"),
        ],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "pr:42",
        "summary": "Add GraphQL layer (Strawberry) for mobile clients alongside REST",
        "reasoning": "Mobile clients were making 5-8 REST calls per screen. GraphQL lets them fetch exactly what they need in one request, reducing latency on cellular networks. We kept REST for server-to-server communication where predictable responses matter more. Strawberry was chosen over Ariadne for its code-first, type-safe approach that integrates well with our Pydantic models.",
        "alternatives": "REST-only with BFF pattern, gRPC",
        "confidence": "high",
        "decision_date": "2024-11-02",
        "entities": [
            ("GraphQL", "technology"),
            ("Strawberry", "library"),
            ("REST", "pattern"),
        ],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "pr:87",
        "summary": "Replace Celery with ARQ for background job processing",
        "reasoning": "Celery was massive overkill — we run ~200 jobs/day, not millions. ARQ is async-native (matches our FastAPI stack), uses Redis as its broker (which we already run), and has a fraction of the operational complexity. Celery required a separate RabbitMQ instance and had opaque failure modes that were hard to debug.",
        "alternatives": "Celery, Dramatiq, Huey",
        "confidence": "high",
        "decision_date": "2024-11-15",
        "entities": [
            ("ARQ", "library"),
            ("Celery", "library"),
            ("Redis", "technology"),
        ],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "pr:103",
        "summary": "Use structlog for structured JSON logging throughout the application",
        "reasoning": "stdlib logging produced unstructured text that was hard to parse in our log aggregator (Datadog). structlog outputs JSON by default, supports context binding (request_id, user_id flow through automatically), and integrates cleanly with FastAPI middleware. This cut our mean-time-to-diagnose production issues from ~45min to ~10min.",
        "alternatives": "stdlib logging with JSON formatter, loguru",
        "confidence": "medium",
        "decision_date": "2024-11-20",
        "entities": [
            ("structlog", "library"),
            ("Datadog", "technology"),
            ("logging", "pattern"),
        ],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "doc:docs/architecture.md",
        "summary": "Follow layered architecture: routers → services → repositories → database",
        "reasoning": "Clean separation of concerns. Routers handle HTTP/GraphQL concerns, services contain business logic, repositories abstract database access. This makes testing straightforward — you can test services without HTTP and repositories without business logic. We explicitly chose NOT to use a hexagonal/ports-and-adapters pattern because it adds indirection we don't need at our scale.",
        "alternatives": "Hexagonal architecture, flat structure, DDD",
        "confidence": "high",
        "decision_date": "2024-09-10",
        "entities": [
            ("layered architecture", "pattern"),
            ("repository pattern", "pattern"),
        ],
    },
]

LEARNINGS = [
    {
        "id": str(uuid.uuid4()),
        "source_id": "session:2024-12-01-auth-bug",
        "category": "bug_fix",
        "summary": "JWT refresh tokens must be rotated BEFORE expiry, not after",
        "detail": "Found a race condition where concurrent requests during token refresh would fail. The refresh token was being invalidated before the new one was issued. Fix: issue the new token first, then invalidate the old one with a 30-second grace period. This affected ~2% of mobile users during peak hours.",
        "components": "auth/tokens.py,middleware/auth.py",
        "session_date": "2024-12-01",
        "entities": [("JWT", "technology"), ("authentication", "pattern")],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "session:2024-12-05-deploy",
        "category": "gotcha",
        "summary": "Docker multi-stage builds break pip cache when COPY order changes",
        "detail": "Build times jumped from 2min to 15min after reordering COPY statements. Docker layer caching is order-dependent — requirements.txt must be copied and installed BEFORE copying application code. Also discovered that using --mount=type=cache for pip dramatically speeds up rebuilds even when the cache layer is invalidated.",
        "components": "Dockerfile",
        "session_date": "2024-12-05",
        "entities": [("Docker", "technology")],
    },
    {
        "id": str(uuid.uuid4()),
        "source_id": "session:2024-12-10-redis",
        "category": "bug_fix",
        "summary": "Redis connection pool must be bounded to prevent connection exhaustion under load",
        "detail": "Production Redis started rejecting connections during a traffic spike. Default redis-py creates unbounded connections. Fix: set max_connections=50 in the ConnectionPool and add health_check_interval=30. Also added a circuit breaker so cache misses fall through to PostgreSQL instead of crashing the request.",
        "components": "cache/redis_client.py,config/settings.py",
        "session_date": "2024-12-10",
        "entities": [("Redis", "technology"), ("connection pooling", "pattern")],
    },
]


def seed(db_path: Path) -> None:
    conn = get_connection(db_path)
    now = datetime.now().isoformat()

    # Insert sources
    for s in SOURCES:
        conn.execute(
            "INSERT OR REPLACE INTO sources (id, source_type, repo, url, title, raw_content, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (s["id"], s["source_type"], s["repo"], s["url"], s["title"], s["raw_content"], now),
        )

    # Insert decisions + entities
    for d in DECISIONS:
        conn.execute(
            "INSERT OR REPLACE INTO decisions (id, source_id, summary, reasoning, alternatives, confidence, decision_date, extracted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (d["id"], d["source_id"], d["summary"], d["reasoning"], d["alternatives"], d["confidence"], d["decision_date"], now),
        )
        for entity_name, entity_type in d["entities"]:
            conn.execute(
                "INSERT OR REPLACE INTO decision_entities (decision_id, entity, entity_type) VALUES (?, ?, ?)",
                (d["id"], entity_name, entity_type),
            )

    # Insert learnings + entities
    for l in LEARNINGS:
        conn.execute(
            "INSERT OR REPLACE INTO learnings (id, source_id, category, summary, detail, components, session_date, extracted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (l["id"], l["source_id"], l["category"], l["summary"], l["detail"], l["components"], l["session_date"], now),
        )
        for entity_name, entity_type in l["entities"]:
            conn.execute(
                "INSERT OR REPLACE INTO learning_entities (learning_id, entity, entity_type) VALUES (?, ?, ?)",
                (l["id"], entity_name, entity_type),
            )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo.db")
    seed(output)
    print(f"Demo database created at {output}")
    print(f"  7 decisions, 3 learnings, 10 sources")
    print(f"\nTry:")
    print(f"  uv run setkontext stats --db-path {output}")
    print(f"  uv run setkontext recall 'redis' --db-path {output}")
