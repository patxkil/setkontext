# setkontext

Extract engineering decisions from your GitHub repository and make them available to AI coding agents (Claude Code, Cursor, etc.) via MCP.

**The problem:** Your team's engineering decisions are scattered across PRs, ADRs, and architecture docs. When an AI agent helps you build features, it doesn't know *why* things are built the way they are — so it makes choices that contradict past decisions.

**setkontext** extracts those decisions, stores them in a local SQLite database, and exposes them to your AI agent through MCP (Model Context Protocol). Your agent can then query decisions like "why did we choose FastAPI?" or get guidance like "how should I add a new API endpoint?" grounded in your team's actual decisions.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- A GitHub personal access token (classic, with `repo` scope)
- An [Anthropic API key](https://console.anthropic.com/)

### Install

```bash
git clone https://github.com/patxkil/setkontext.git
cd setkontext
uv sync
```

### Set up in your project

Navigate to the project where you want decisions available:

```bash
cd /path/to/your/project

# Initialize setkontext (creates .env, .mcp.json, updates .gitignore)
uv run --directory /path/to/setkontext setkontext init owner/repo
```

This will prompt for your GitHub token and Anthropic API key, then:
1. Save credentials to `.env` (gitignored)
2. Create `.mcp.json` so Claude Code / Cursor auto-discover the MCP server
3. Add `setkontext.db` and `.env` to `.gitignore`

### Extract decisions

```bash
uv run --directory /path/to/setkontext setkontext extract
```

This fetches ADRs, architecture docs, and merged PRs from your repository, then uses Claude to extract engineering decisions. Results are stored in `setkontext.db` in your project directory.

### Use with AI agents

**Claude Code / Cursor (MCP — recommended):**
Restart Claude Code after running `init`. It picks up `.mcp.json` and your agent gets these tools:
- `query_decisions` — Ask questions like "why did we choose Postgres?" or "how should I add caching?"
- `get_decisions_by_entity` — Find all decisions about a specific technology
- `list_entities` — See all technologies/patterns that have decisions
- `get_decision_context` — Get full details on a specific decision

**Static context file (any agent):**
```bash
# Generate CLAUDE.md (for Claude Code)
uv run --directory /path/to/setkontext setkontext generate

# Generate .cursorrules (for Cursor)
uv run --directory /path/to/setkontext setkontext generate -f cursor
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `setkontext init owner/repo` | Full project setup (credentials + MCP + gitignore) |
| `setkontext extract` | Extract decisions from GitHub |
| `setkontext query "question"` | Ask a question about decisions |
| `setkontext stats` | Show extraction statistics |
| `setkontext generate` | Generate a static context file |
| `setkontext serve` | Start MCP server (called automatically by Claude Code) |

## What gets extracted

- **ADRs** (Architecture Decision Records) — parsed deterministically from standard formats (Nygard, MADR)
- **Documentation** — architecture docs, strategy docs, and other markdown files analyzed by Claude
- **Pull Requests** — merged PRs analyzed for implicit engineering decisions

## How it works

1. **Fetch** — pulls ADRs, docs, and PRs from your GitHub repository
2. **Extract** — Claude identifies engineering decisions, reasoning, alternatives, and related technologies
3. **Store** — decisions go into a local SQLite database with full-text search (FTS5)
4. **Query** — MCP server or CLI lets you (or your AI agent) ask questions grounded in your team's actual decisions

## Early Alpha

This is v0.1.0. Expect rough edges. Known limitations:
- Only GitHub repositories (no GitLab/Bitbucket yet)
- Extraction uses Anthropic API (costs ~$0.01-0.10 per run depending on repo size)
- No incremental extraction yet (re-running extract processes everything again, but merges results)

## Feedback

This is an early alpha. If something breaks or you have ideas, open an issue or message me directly.
