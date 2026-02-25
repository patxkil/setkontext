# setkontext Demo Recording Script

**Target length:** 2 minutes
**Tool:** [asciinema](https://asciinema.org/) for terminal recording, or screen record with OBS/QuickTime

---

## Setup (before recording)

1. Have a test repo with some merged PRs and an ADR or two (your own repo works)
2. Have `ANTHROPIC_API_KEY` set in your environment
3. Have `SETKONTEXT_GITHUB_TOKEN` set (a classic PAT with `repo` scope)
4. Clean slate: `rm -f setkontext.db .env .mcp.json`
5. Make your terminal font large (14-16pt), dark background, 80 columns max

## Recording Script

### Scene 1: Init (0:00 - 0:20)

```
# Start with a clean directory, show what setkontext does
setkontext init patxkil/setkontext
```

**What to say (voiceover or captions):**
> "setkontext connects to your GitHub repo and sets up everything for AI agents to understand your team's decisions."

Pause to show the output — it creates `.env`, `.mcp.json`, updates `.gitignore`.

---

### Scene 2: Extract (0:20 - 1:00)

```
setkontext extract --pr-limit 10
```

**What to say:**
> "Extract scans your merged PRs, ADRs, and docs. It uses Claude to identify the engineering decisions buried in them."

Let it run. The Rich progress output looks good on camera. Show the summary at the end — "Found X decisions from Y sources."

Then show stats:

```
setkontext stats
```

---

### Scene 3: Query (1:00 - 1:30)

```
setkontext query "Why did we choose SQLite for storage?"
```

**What to say:**
> "Now any AI agent — or you — can ask questions and get answers grounded in your actual decisions, with source links."

Show the answer with source references.

---

### Scene 4: The Payoff — MCP in Action (1:30 - 2:00)

```
# Show the .mcp.json that was created
cat .mcp.json
```

**What to say:**
> "This is the real point. That .mcp.json means Claude Code and Cursor can query your decisions live while coding. When an agent is about to make a technical choice, it checks against what your team already decided."

End with:

```
setkontext query "How should I add a new API endpoint?"
```

Show the answer that references actual decisions as constraints.

---

## Tips

- **Speed:** Type at a natural pace. Silence is fine while commands run.
- **Errors:** If extraction finds 0 decisions, pick a repo with meatier PRs.
- **asciinema:** `asciinema rec demo.cast` then `asciinema upload demo.cast` — gives you a shareable link and embeddable player.
- **GIF alternative:** Use [agg](https://github.com/asciinema/agg) to convert the cast to a GIF for the README.
