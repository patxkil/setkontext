# CLAUDE.md — setkontext

## What is setkontext

The decision memory layer for AI coding agents. Automatically extracts engineering decisions from GitHub (PRs, ADRs, docs), captures session learnings (bugs fixed, gotchas, implementations), and consolidates recurring patterns into reusable knowledge. Agents query this via MCP tools so they understand *why* code is the way it is.

**Not** a general-purpose context database. setkontext owns the *why* — decisions, learnings, and the flywheel between them.

## Product positioning

- **Competitor landscape:** OpenViking (ByteDance) is a general-purpose "context database for agents" — filesystem paradigm, vector search, tiered loading. setkontext is domain-specific: engineering decisions and session memory with zero-effort extraction.
- **Defensible moats:** (1) Auto-extraction pipeline from GitHub, (2) learning→decision consolidation flywheel, (3) decision validation & drift detection.
- **Monetization:** Free single-user forever. Team features (sync, multi-repo, onboarding) are the paid tier.

## Current roadmap priority (Phase 0)

Building toward "first 5 minutes are magical, database stays fresh without effort":

1. **P0.2 — Smart PR filtering** — Skip bot PRs, empty bodies, docs-only changes before hitting Claude. ~50% cost reduction. New `github/filter.py` module.
2. **P0.1 — Incremental extraction** — Track watermarks per source type, only process new PRs. Unlocks watch mode.
3. **P0.3 — Tiered context (L0/L1/L2)** — Return summaries by default, full text on demand. Schema migration v3→v4.
4. **P0.4 — Watch mode** — Background daemon polling for new merged PRs.
5. **P0.5 — Single-command init** — `setkontext init` does extract + index + configure in one step.
6. **P0.6 — Source deduplication** — Merge duplicate decisions across sources.

## Tech stack

- **Language:** Python 3.11+
- **Package manager:** uv (use `uv run` for all commands)
- **CLI:** Typer + Rich
- **Database:** SQLite + FTS5 (WAL mode), raw SQL (no ORM)
- **AI:** Anthropic Claude API (direct SDK, not LangChain)
- **Agent integration:** MCP over stdio (9 tools)
- **GitHub:** PyGithub
- **Build:** Hatchling (PEP 621)

## Project structure

```
setkontext/
├── cli.py              # Typer CLI — all commands (init, extract, query, recall, etc.)
├── mcp_server.py       # MCP server — 9 tools exposed to agents
├── config.py           # Config loading (.env, env vars)
├── activity.py         # Activity logging (tool call tracking)
├── context.py          # Context file generation (CLAUDE.md, .cursorrules)
├── github/
│   ├── fetcher.py      # GitHub API client — fetches PRs, ADRs, docs
│   └── (filter.py)     # [PLANNED] Smart PR filtering before extraction
├── extraction/
│   ├── models.py       # Dataclasses: Decision, Learning, Source, Entity, etc.
│   ├── pr_extractor.py # Claude-powered PR decision extraction
│   ├── adr_parser.py   # Deterministic ADR parsing (Nygard, MADR formats)
│   └── doc_extractor.py # Claude-powered doc extraction
├── query/
│   ├── engine.py       # QueryEngine — FTS5 search + Claude synthesis
│   └── validator.py    # DecisionValidator — conflict detection
├── storage/
│   ├── db.py           # SQLite schema, migrations, connection management
│   └── repository.py   # CRUD operations, search, entity queries
└── entire/             # Entire.io session transcript extraction (optional)
```

## Development commands

```bash
uv run pytest                         # Run tests
uv run setkontext --help              # CLI help
uv run setkontext extract             # Extract decisions from GitHub
uv run setkontext query "question"    # Query decisions
uv run setkontext serve               # Start MCP server
```

## Key conventions

- **No ORM.** Raw SQL in `storage/repository.py`. Keep queries simple and debuggable.
- **Dataclasses for models.** All data structures in `extraction/models.py`. No Pydantic.
- **Claude for unstructured, deterministic for structured.** ADRs get regex parsing. PRs/docs get Claude. Don't use Claude when parsing works.
- **Human-in-the-loop for decisions.** Never auto-create decisions silently. Propose and confirm.
- **Local-first.** Everything works offline once extracted. No external services at runtime except MCP tool calls that need Claude.
- **Quality over quantity.** Fewer, high-confidence decisions beat many noisy ones.
- **Activity logging.** All MCP tool calls log to `setkontext-activity.jsonl`. Maintain this for observability.

## Database schema (v3)

7 tables: `sources`, `decisions`, `learnings`, `decision_entities`, `learning_entities`, `entity_relationships`, `file_references` + FTS5 virtual table `decisions_fts`.

Decision IDs are currently UUID v4 (random). Planned: switch to UUID v5 (deterministic from source + content) for idempotent re-extraction.

## When making changes

- Run `uv run pytest` after changes. Tests are in `tests/`.
- Don't add dependencies without good reason. The dependency tree is intentionally small.
- Don't introduce ORMs, LangChain, or heavy frameworks.
- Keep CLI commands consistent: all use `--db-path` and `--log-path` optional overrides.
- MCP tools must log activity via `log_activity()` in `activity.py`.
- Schema changes require a migration in `storage/db.py` and version bump.
