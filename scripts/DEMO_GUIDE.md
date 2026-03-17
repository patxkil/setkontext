# How to Record the setkontext Demo GIF

## What you'll show

A 30-second terminal recording of:
1. `setkontext stats` — look at what was extracted (3 sec)
2. `setkontext recall "redis"` — find a past bug fix (5 sec)
3. `setkontext query "why did we choose FastAPI?"` — the magic moment (10 sec)

## Setup (one time, ~2 minutes)

### 1. Create the demo database

```bash
cd /path/to/setkontext
uv run python scripts/seed_demo_db.py demo.db
```

This creates a pre-populated database with 7 decisions and 3 learnings
from a fictional "acme/backend" project. No API keys needed.

### 2. Test that it works

```bash
uv run setkontext stats --db-path demo.db
uv run setkontext recall "redis" --db-path demo.db
```

You should see formatted output with decisions and learnings.

### 3. Note about `query`

The `query` command requires an Anthropic API key (it uses Claude to
synthesize an answer). Two options:

**Option A — Use `query` for real (recommended, costs ~$0.01):**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run setkontext query "why did we choose FastAPI?" --db-path demo.db
```

**Option B — Skip `query`, just show `stats` + `recall`:**
The recall command already shows the "memory" magic. You can demo
without the query command if you don't want to set up an API key.

## Recording

### Easiest: Mac screen recording → GIF

1. Open Terminal, make it look clean:
   - Font size ~16pt (Cmd+Plus to enlarge)
   - Dark background
   - Clear the screen (`clear`)
   - Resize window to ~80 columns wide, ~24 rows tall

2. Start recording: **Cmd+Shift+5** → "Record Selected Portion"
   - Draw the box around your terminal window
   - Click "Record"

3. Run the demo script below (type it manually for a natural feel):

```
$ uv run setkontext stats --db-path demo.db
                                          ← pause 3 sec, let output settle

$ uv run setkontext recall "redis" --db-path demo.db
                                          ← pause 3 sec

$ uv run setkontext query "why did we choose FastAPI?" --db-path demo.db
                                          ← pause 5 sec, let answer render
```

4. Stop recording: click the stop button in the menu bar

5. Convert to GIF:
   - Go to https://ezgif.com/video-to-gif
   - Upload the .mov file
   - Set width to 800px
   - Click "Convert to GIF"
   - Download

### Alternative: asciinema (shareable link, no GIF conversion needed)

```bash
brew install asciinema
asciinema rec demo.cast
# run your commands, then Ctrl+D to stop
# Upload: asciinema upload demo.cast
# Or convert to GIF: brew install agg && agg demo.cast demo.gif
```

## Tips for a good recording

- **Type at a natural pace** — too fast looks robotic, too slow is boring
- **Pause after each command** — let the viewer read the output
- **Don't make typos** — re-record if needed, it's only 30 seconds
- **Clear between commands** is optional — scrolling output looks dynamic
- **Keep it under 30 seconds** — people drop off fast

## Where to put the GIF

Add it to the README right after the project description:

```markdown
![setkontext demo](docs/demo.gif)
```

Commit the GIF to `docs/demo.gif` in the repo.
