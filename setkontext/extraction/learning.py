"""Session learning extraction using Claude.

Analyzes AI coding session transcripts to extract operational knowledge:
bugs solved, gotchas discovered, and features implemented. Unlike decision
extraction which focuses on WHY, learning extraction focuses on WHAT happened
and what to watch out for.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime

import anthropic

from setkontext.extraction.models import Entity, Learning, Source

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds
MAX_TOKENS = 2048

EXTRACTION_PROMPT = """\
You are a session knowledge extractor. Analyze the following AI coding session \
transcript and extract practical learnings: bugs that were fixed, gotchas that \
were discovered, and features that were implemented.

This is a transcript from an AI coding agent (like Claude Code or Cursor) working \
on a codebase. Your job is to find actionable knowledge that would help a future \
developer or AI agent working in the same codebase.

Extract three categories of learnings:

**bug_fix** — A bug that was identified and fixed:
- What were the symptoms?
- What was the root cause?
- How was it fixed?
- Which files/components were involved?

**gotcha** — A non-obvious pitfall or surprising behavior discovered:
- What was surprising or unexpected?
- Why does it happen?
- What's the workaround or correct approach?

**implementation** — A feature or system that was built and is working:
- What was implemented?
- Key design choices made during implementation
- How does it work at a high level?
- Which components are involved?

Ignore routine, trivial changes (typo fixes, comment updates, formatting). \
Focus on knowledge that would save time if someone encounters the same area again.

## Session Info

{session_info}

## Transcript

{transcript}

## Instructions

Respond with a JSON object:
{{"learnings": [
  {{
    "category": "bug_fix|gotcha|implementation",
    "summary": "One sentence describing what was learned",
    "detail": "Full context: root cause, fix, key details a future developer needs",
    "components": ["path/to/file.py", "module_name"],
    "entities": [
      {{"name": "technology or concept", "entity_type": "technology|pattern|service|library"}}
    ]
  }}
]}}

If the session contains no meaningful learnings (e.g., just exploration or \
reading code), return {{"learnings": []}}.

Respond ONLY with valid JSON, no other text.
"""


def extract_session_learnings(
    transcript: str,
    repo: str,
    client: anthropic.Anthropic,
    session_metadata: dict | None = None,
) -> tuple[Source, list[Learning]]:
    """Analyze a session transcript for bugs, gotchas, and implementations.

    Args:
        transcript: The session transcript text (condensed or raw).
        repo: Repository identifier (owner/repo).
        client: Anthropic API client.
        session_metadata: Optional dict with keys like agent, branch, prompt, summary.

    Returns:
        A Source and list of Learnings extracted from the session.
    """
    meta = session_metadata or {}
    source_id = f"learning:{meta.get('session_id', uuid.uuid4().hex[:12])}"

    source = Source(
        id=source_id,
        source_type="learning",
        repo=repo,
        url="",
        title=_build_title(meta),
        raw_content=transcript[:5000],  # Store a preview, not the full transcript
        fetched_at=datetime.now(),
    )

    session_info = _build_session_info(meta)

    # Truncate transcript for the prompt
    if len(transcript) > 15000:
        transcript = transcript[:15000] + "\n\n... (truncated)"

    prompt = EXTRACTION_PROMPT.format(
        session_info=session_info,
        transcript=transcript,
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(f"Rate limited, retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"Rate limited after {MAX_RETRIES} retries, skipping")
                return source, []
        except anthropic.APIError as e:
            logger.error(f"API error during learning extraction: {e}")
            return source, []

    learnings = _parse_response(response, source.id)
    return source, learnings


def _build_title(meta: dict) -> str:
    """Build a readable title for the learning source."""
    agent = meta.get("agent", "unknown")
    if meta.get("prompt"):
        first_line = meta["prompt"].split("\n")[0].strip()
        if len(first_line) > 80:
            first_line = first_line[:77] + "..."
        return f"[{agent}] {first_line}"
    if meta.get("summary"):
        summary = meta["summary"]
        if len(summary) > 80:
            summary = summary[:77] + "..."
        return f"[{agent}] {summary}"
    return f"[{agent}] Session {meta.get('session_id', 'unknown')[:8]}"


def _build_session_info(meta: dict) -> str:
    """Build the session info section for the prompt."""
    parts: list[str] = []
    if meta.get("agent"):
        parts.append(f"**Agent:** {meta['agent']}")
    if meta.get("branch"):
        parts.append(f"**Branch:** {meta['branch']}")
    if meta.get("prompt"):
        parts.append(f"**Initial Prompt:** {meta['prompt'][:200]}")
    if meta.get("summary"):
        parts.append(f"**Summary:** {meta['summary'][:200]}")
    if meta.get("files_touched"):
        files = meta["files_touched"]
        if isinstance(files, list):
            files = ", ".join(files[:20])
        parts.append(f"**Files Touched:** {files}")
    return "\n".join(parts) if parts else "(no session metadata available)"


def _parse_response(
    response: anthropic.types.Message, source_id: str
) -> list[Learning]:
    """Parse Claude's JSON response into Learning objects."""
    if not response.content:
        logger.warning(f"Empty response for source {source_id}")
        return []
    text = response.content[0].text.strip()

    # Handle markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse JSON for source {source_id}: {text[:200]}")
        return []

    valid_categories = {"bug_fix", "gotcha", "implementation"}
    learnings: list[Learning] = []

    for item in data.get("learnings", []):
        category = item.get("category", "")
        if category not in valid_categories:
            logger.warning(f"Skipping learning with invalid category: {category}")
            continue

        entities = [
            Entity(name=e["name"], entity_type=e.get("entity_type", "technology"))
            for e in item.get("entities", [])
        ]

        learnings.append(
            Learning(
                id=str(uuid.uuid4()),
                source_id=source_id,
                category=category,
                summary=item.get("summary", ""),
                detail=item.get("detail", ""),
                components=item.get("components", []),
                entities=entities,
                session_date=datetime.now().strftime("%Y-%m-%d"),
                extracted_at=datetime.now(),
            )
        )

    return learnings
