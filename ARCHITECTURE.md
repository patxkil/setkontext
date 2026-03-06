# Architecture Decisions

## 1. Python + Typer for CLI

**Decision:** Use Python as the primary language and Typer as the CLI framework.

**Reasoning:** Python has the richest ecosystem for AI/LLM integration (Anthropic SDK, MCP SDK). Typer provides automatic --help generation, type-safe arguments via type hints, and Rich integration for colored terminal output. Alternatives considered: Go (faster binary but weaker AI SDK support), Click (more verbose than Typer), argparse (too low-level).

**Alternatives rejected:** Go, Node.js, Click, argparse

## 2. SQLite with FTS5 for local storage

**Decision:** Store all decisions and learnings in a local SQLite database with FTS5 full-text search.

**Reasoning:** SQLite is zero-config, file-based, and ships with Python. Users don't need to install or manage a database server. FTS5 enables fast keyword search over decision summaries and learnings without external search infrastructure. WAL mode is enabled for concurrent read access from the MCP server. Alternatives considered: PostgreSQL (too heavy for a CLI tool), JSON files (no query capability), Elasticsearch (massive overkill).

**Alternatives rejected:** PostgreSQL, JSON files, Elasticsearch, ChromaDB

## 3. MCP (Model Context Protocol) for agent integration

**Decision:** Expose decisions to AI agents via MCP over stdio transport.

**Reasoning:** MCP is the emerging standard for tool integration with AI coding agents. Claude Code and Cursor both support MCP natively. Using stdio transport means no HTTP server to manage — the agent spawns the MCP server as a subprocess. This gives agents 8 specialized tools (query_decisions, validate_approach, recall_learnings, etc.) instead of dumping all context into a static file. Alternatives considered: static CLAUDE.md file (no interactivity), HTTP API (requires running server), Language Server Protocol (wrong abstraction).

**Alternatives rejected:** HTTP REST API, static context files only, Language Server Protocol

## 4. Claude API (Anthropic) for extraction and synthesis

**Decision:** Use the Anthropic Claude API for extracting decisions from PRs/docs and for synthesizing query answers.

**Reasoning:** Decision extraction requires understanding nuanced engineering tradeoffs in PR descriptions and architecture docs — this is a natural language understanding task. Claude handles structured extraction well (outputting JSON with decisions, entities, relationships). Using the API directly (not a framework like LangChain) keeps the dependency tree small and the code debuggable. Alternatives considered: OpenAI API (works but Anthropic SDK has better structured output), local models (too slow and inaccurate for extraction), regex/heuristic parsing (too brittle for PR descriptions).

**Alternatives rejected:** OpenAI API, LangChain, local LLMs, regex parsing

## 5. Entity-based knowledge graph

**Decision:** Tag each decision with entities (technologies, patterns, services) and track relationships between entities.

**Reasoning:** Entities allow graph-based navigation: "show me everything about PostgreSQL" or "what depends on FastAPI?". Relationship types (uses, replaces, depends_on, conflicts_with) enable the validate_approach tool to detect conflicts. This is more useful than flat keyword search alone. The entity graph is stored in SQLite (entity_relationships table) rather than a dedicated graph database to keep things simple.

**Alternatives rejected:** Flat keyword tagging, dedicated graph database (Neo4j), vector embeddings only

## 6. uv as the Python package manager

**Decision:** Use uv for dependency management and running the project.

**Reasoning:** uv is significantly faster than pip and provides reliable lockfiles (uv.lock). It handles virtual environments automatically. The `uv run` command ensures the correct environment is always used. uv also supports `uv tool install` for installing setkontext as a global CLI tool. Alternatives considered: pip + venv (slower, no lockfile), poetry (heavier, slower), conda (wrong use case).

**Alternatives rejected:** pip + venv, poetry, conda, pipx

## 7. Dataclass models (no ORM)

**Decision:** Use plain Python dataclasses for data models and raw SQL for database operations.

**Reasoning:** The schema is simple (7 tables) and the queries are straightforward. An ORM would add complexity without real benefit at this scale. Dataclasses provide type hints and clean constructors without framework overhead. The Repository class wraps all SQL queries in one place, making it easy to test and modify. Alternatives considered: SQLAlchemy (too heavy), Pydantic (good for validation but not needed internally), Django ORM (way too heavy).

**Alternatives rejected:** SQLAlchemy, Pydantic models, Django ORM

## 8. Hatchling as build backend

**Decision:** Use Hatchling for building the Python package.

**Reasoning:** Hatchling is lightweight, fast, and works well with uv. It follows modern Python packaging standards (pyproject.toml, PEP 621). No setup.py or setup.cfg needed. Alternatives considered: setuptools (legacy, more config), flit (simpler but less flexible), poetry-core (tied to poetry ecosystem).

**Alternatives rejected:** setuptools, flit, poetry-core

## 9. File-based configuration via .env

**Decision:** Store credentials (GitHub token, Anthropic API key) in a .env file per project.

**Reasoning:** .env files are a well-understood pattern for secrets. python-dotenv loads them automatically. The `init` command creates the .env and adds it to .gitignore so secrets never get committed. Environment variables can override .env values for CI/CD use. Alternatives considered: system keychain (platform-specific complexity), config file in ~/.config (harder to manage per-project), encrypted config (overkill for local dev tool).

**Alternatives rejected:** system keychain, global config file, encrypted config

## 10. Deterministic ADR parsing + LLM extraction for PRs

**Decision:** Parse ADRs deterministically using format detection (Nygard, MADR) but use Claude for PR decision extraction.

**Reasoning:** ADRs follow known formats with clear structure (Status, Context, Decision sections) — regex/parsing is reliable and free. PRs contain unstructured natural language where decisions are implicit — this requires LLM understanding. This hybrid approach minimizes API costs while maximizing extraction quality. Alternatives considered: LLM for everything (expensive, slower), deterministic only (misses PR decisions), embedding similarity (doesn't extract structured decisions).

**Alternatives rejected:** LLM-only extraction, deterministic-only parsing, embedding-based approach

## 11. Learning consolidation with human-in-the-loop

**Decision:** Automatically detect recurring learning patterns but require human confirmation to promote them into decisions.

**Reasoning:** Session learnings accumulate automatically via the `capture` hook. When the same entity (e.g., "Redis") appears in multiple learnings across sessions, it often signals an implicit engineering decision. The `consolidate` command groups learnings by shared entities, sends each cluster to Claude to assess if it warrants a decision, then presents proposals interactively. This follows the "auto-detect, propose, human-confirm" pattern — decisions are never created silently because they're high-trust objects that guide future agent behavior. Agents are notified of pending patterns via the `get_session_briefing` MCP tool.

**Alternatives rejected:** Fully automatic consolidation (risk of polluting decisions), manual-only review (no one would do it), time-based batching (arbitrary, misses patterns)
