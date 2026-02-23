# setkontext

Extract engineering decisions from your GitHub repository and make them available to AI coding agents (Claude Code, Cursor, etc.) via MCP.

**The problem:** Your team's engineering decisions are scattered across PRs, ADRs, and architecture docs. When an AI agent helps you build features, it doesn't know *why* things are built the way they are — so it makes choices that contradict past decisions.

**setkontext** extracts those decisions, stores them in a local SQLite database, and exposes them to your AI agent through MCP (Model Context Protocol). Your agent can then query decisions like "why did we choose FastAPI?" or get guidance like "how should I add a new API endpoint?" grounded in your team's actual decisions.

## Quick Start

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A GitHub personal access token (classic, with `repo` scope) — [create one here](https://github.com/settings/tokens)
- An Anthropic API key — [get one here](https://console.anthropic.com/) (needed for extraction and queries, costs ~$0.01-0.10 per extraction run)

### 1. Install setkontext

```bash
git clone https://github.com/patxkil/setkontext.git
cd setkontext
uv tool install .
```

This installs `setkontext` as a global CLI tool. Verify it works:

```bash
setkontext --help
```

### 2. Set up in your project

Go to the project where you want engineering decisions available:

```bash
cd /path/to/your/project
setkontext init owner/repo
```

It will prompt for your GitHub token and Anthropic API key, then:
1. Save credentials to `.env` (gitignored)
2. Create `.mcp.json` so Claude Code / Cursor auto-discover the MCP server
3. Add `setkontext.db` and `.env` to your `.gitignore`

### 3. Extract decisions

```bash
setkontext extract
```

This fetches ADRs, architecture docs, and merged PRs from your repository, then uses Claude to extract engineering decisions. Results are stored in `setkontext.db` in your project directory.

### 4. Use with your AI agent

**Claude Code / Cursor (MCP — recommended):**

Restart Claude Code after running `init`. It picks up `.mcp.json` automatically and your agent gets these tools:
- `query_decisions` — "why did we choose Postgres?" or "how should I add caching?"
- `get_decisions_by_entity` — all decisions about a specific technology
- `list_entities` — see all technologies/patterns that have decisions
- `get_decision_context` — full details on a specific decision

**Static context file (any agent):**
```bash
setkontext generate            # Creates CLAUDE.md
setkontext generate -f cursor  # Creates .cursorrules
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
- Extraction and queries use the Anthropic API — you need your own API key
- No incremental extraction yet (re-running extract processes everything again, but merges results)

## Feedback

This is an early alpha. If something breaks or you have ideas, open an issue or message me directly.
