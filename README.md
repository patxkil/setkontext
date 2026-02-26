# setkontext

Engineering context for AI coding agents — decisions from your GitHub history + learnings from your coding sessions.

**The problem:** Your team's engineering decisions are scattered across PRs, ADRs, and architecture docs. And every new AI agent session starts from zero — it forgets the bugs you solved, the gotchas you discovered, and the conventions you established last time.

**setkontext** solves both:
1. **Decisions** — extracts engineering decisions from your GitHub repo (ADRs, PRs, docs) so your agent knows *why* things are built the way they are
2. **Session memory** — automatically captures bugs solved, gotchas discovered, and features implemented across AI coding sessions so your agent doesn't repeat mistakes

Everything is stored locally in SQLite with full-text search and exposed to your agent via MCP (Model Context Protocol).

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
3. Configure Claude Code hooks to auto-capture session learnings
4. Add `setkontext.db` and `.env` to your `.gitignore`

### 3. Extract decisions

```bash
setkontext extract
```

This fetches ADRs, architecture docs, and merged PRs from your repository, then uses Claude to extract engineering decisions. Results are stored in `setkontext.db` in your project directory.

### 4. Use with your AI agent

**Claude Code / Cursor (MCP — recommended):**

Restart Claude Code after running `init`. It picks up `.mcp.json` automatically and your agent gets these tools:
- `query_decisions` — "why did we choose Postgres?" or "how should I add caching?"
- `validate_approach` — checks if a proposed implementation conflicts with existing decisions
- `get_decisions_by_entity` — all decisions about a specific technology
- `list_entities` — see all technologies/patterns that have decisions
- `get_decision_context` — full project decision summary
- `recall_learnings` — search past session learnings (bugs, gotchas, implementations)

Session learnings are captured automatically at the end of each Claude Code session via hooks. No extra work needed.

**Static context file (any agent):**
```bash
setkontext generate            # Creates CLAUDE.md (includes decisions + learnings)
setkontext generate -f cursor  # Creates .cursorrules
```

### 5. Save and recall learnings

Learnings are captured automatically from session transcripts. You can also save them manually:

```bash
# Save a bug fix
setkontext remember -c bug_fix -s "Fixed race condition in session cleanup"

# Save a gotcha
echo "Token refresh must happen BEFORE expiry, not after" | \
  setkontext remember -c gotcha -s "JWT refresh token timing"

# Save an implementation
setkontext remember -c implementation -s "Added Redis caching with 5-min TTL"
```

Search learnings from the CLI:

```bash
setkontext recall "authentication bugs"
setkontext recall "deployment" --category gotcha
```

### 6. See what your agent received

After your agent has used setkontext tools, review what context it got:

```bash
setkontext activity                           # last 20 tool calls
setkontext activity --tool validate_approach  # just validation checks
setkontext activity --json                    # raw JSONL for scripting
```

Example output:
```
14:30:45 validate_approach
  Approach: "Use MongoDB for caching"
  → CONFLICTS (1 conflict(s)), 456ms

14:31:02 query_decisions
  Question: "Why did we choose FastAPI?"
  → 234ms, 3 decision(s) matched
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `setkontext init owner/repo` | Full project setup (credentials + MCP + hooks + gitignore) |
| `setkontext extract` | Extract decisions from GitHub |
| `setkontext extract --include-sessions` | Also extract from Entire.io agent sessions |
| `setkontext query "question"` | Ask a question about decisions |
| `setkontext remember -c category -s "summary"` | Manually save a learning (bug_fix, gotcha, implementation) |
| `setkontext recall "query"` | Search past learnings |
| `setkontext capture` | Capture learnings from stdin (called by SessionEnd hook) |
| `setkontext activity` | Show recent MCP tool calls and what context agents received |
| `setkontext stats` | Show extraction and learning statistics |
| `setkontext generate` | Generate a static context file (includes learnings) |
| `setkontext serve` | Start MCP server (called automatically by Claude Code) |

## What gets extracted

### Decisions (from GitHub)
- **ADRs** (Architecture Decision Records) — parsed deterministically from standard formats (Nygard, MADR)
- **Documentation** — architecture docs, strategy docs, and other markdown files analyzed by Claude
- **Pull Requests** — merged PRs analyzed for implicit engineering decisions
- **Agent sessions** — Entire.io session transcripts analyzed for decisions made during AI-assisted coding (opt-in via `--include-sessions`)

### Learnings (from coding sessions)
- **Bug fixes** — what was wrong, root cause, how it was fixed, affected components
- **Gotchas** — non-obvious pitfalls, surprising behavior, workarounds
- **Implementations** — features built, key design choices, how they work

Learnings are captured automatically at the end of each Claude Code session, or saved manually with `setkontext remember`.

## How it works

```
GitHub Repository                AI Coding Sessions
    |                                    |
    v                                    v
Fetch (ADRs, docs, PRs)         SessionEnd hook / manual save
    |                                    |
    v                                    v
Extract decisions (Claude)       Extract learnings (Claude)
    |                                    |
    v                                    v
    +-----> SQLite + FTS5 <--------------+
                |
                v
        MCP Server (6 tools)
                |
                v
        AI Agent (Claude Code / Cursor)
```

1. **Fetch** — pulls ADRs, docs, and PRs from your GitHub repository
2. **Extract** — Claude identifies decisions (reasoning, alternatives, technologies) and learnings (bugs, gotchas, implementations)
3. **Store** — everything goes into a local SQLite database with full-text search (FTS5)
4. **Query** — MCP server or CLI lets you (or your AI agent) ask questions grounded in your team's actual decisions and learnings

## Early Alpha

This is v0.1.0. Expect rough edges. Known limitations:
- Only GitHub repositories (no GitLab/Bitbucket yet)
- Session capture hooks work with Claude Code only (Cursor support planned)
- Extraction and queries use the Anthropic API — you need your own API key
- No incremental extraction yet (re-running extract processes everything again, but merges results)

## Feedback

This is an early alpha. If something breaks or you have ideas, open an issue or message me directly.
