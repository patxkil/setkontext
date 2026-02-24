"""Session transcript decision extraction using Claude.

Analyzes Entire.io agent session transcripts to find engineering decisions
made during AI-assisted coding sessions. These are implicit decisions —
an agent chose a library, pattern, or approach while implementing a feature.

The extraction prompt is tuned for transcripts: long, conversational, and
containing a mix of code, tool calls, and discussion.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime

import anthropic

from setkontext.entire.fetcher import SessionData
from setkontext.extraction.models import Decision, Entity, Source

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds

# Larger max_tokens for sessions — transcripts can surface many decisions
MAX_TOKENS = 2048

EXTRACTION_PROMPT = """\
You are an engineering decision extractor. Analyze the following AI agent session \
transcript and extract any significant engineering decisions that were made.

This is a transcript from an AI coding agent (like Claude Code or Cursor) working \
on a codebase. The agent and user discussed and implemented changes. Your job is to \
find moments where a technical choice was made that affects the system's architecture, \
technology stack, patterns, or approach.

Look for decisions like:
- Choosing a library, framework, or tool
- Adopting an architectural pattern or design approach
- Making a tradeoff (performance vs. simplicity, etc.)
- Choosing a data model or API design
- Deciding on a testing strategy or deployment approach
- Choosing between build vs. buy

Ignore routine implementation details — focus on choices that a future developer or AI \
agent would need to know about to understand WHY the system is built the way it is.

## Session Info

**Agent:** {agent}
**Branch:** {branch}
**Initial Prompt:** {prompt}
**Files Touched:** {files_touched}
**Session Summary:** {summary}

## Transcript (condensed)

{transcript}

## Instructions

Respond with a JSON object:
{{"decisions": [
  {{
    "summary": "One sentence describing what was decided",
    "reasoning": "Why this choice was made, including tradeoffs discussed",
    "alternatives": ["Alternative that was considered or rejected"],
    "entities": [
      {{"name": "technology or concept name", "entity_type": "technology|pattern|service|library"}}
    ],
    "confidence": "high|medium|low"
  }}
]}}

If the session contains no engineering decisions (e.g., just a bug fix following \
existing patterns), return {{"decisions": []}}.

Confidence levels:
- high: Decision was explicitly discussed and agreed upon
- medium: Decision was made implicitly by the agent's implementation choice
- low: Decision might be inferred but wasn't directly addressed

Respond ONLY with valid JSON, no other text.
"""


def extract_session_decisions(
    session: SessionData, repo: str, client: anthropic.Anthropic
) -> tuple[Source, list[Decision]]:
    """Analyze an agent session transcript for engineering decisions.

    Returns a Source and list of Decisions (usually 0-2).
    """
    source = Source(
        id=f"session:{session.checkpoint_id}",
        source_type="session",
        repo=repo,
        url="",  # Sessions don't have a URL
        title=_build_title(session),
        raw_content=_build_raw_content(session),
        fetched_at=datetime.now(),
    )

    # Condense transcript for the prompt — full transcripts can be huge
    condensed = _condense_transcript(session.transcript)

    prompt = EXTRACTION_PROMPT.format(
        agent=session.agent,
        branch=session.branch,
        prompt=session.prompt or "(no prompt recorded)",
        files_touched=", ".join(session.files_touched[:20]) if session.files_touched else "(none)",
        summary=session.summary or "(no summary)",
        transcript=condensed,
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
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Rate limited on session {session.checkpoint_id}, retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(
                    f"Rate limited on session {session.checkpoint_id} "
                    f"after {MAX_RETRIES} retries, skipping"
                )
                return source, []
        except anthropic.APIError as e:
            logger.error(f"API error analyzing session {session.checkpoint_id}: {e}")
            return source, []

    decisions = _parse_response(response, source.id, session.session_id)
    return source, decisions


def _build_title(session: SessionData) -> str:
    """Build a readable title for the session source."""
    if session.prompt:
        # Use first line of prompt, truncated
        first_line = session.prompt.split("\n")[0].strip()
        if len(first_line) > 80:
            first_line = first_line[:77] + "..."
        return f"[{session.agent}] {first_line}"
    if session.summary:
        summary = session.summary
        if len(summary) > 80:
            summary = summary[:77] + "..."
        return f"[{session.agent}] {summary}"
    return f"[{session.agent}] Session {session.checkpoint_id[:8]}"


def _build_raw_content(session: SessionData) -> str:
    """Build the full text for storage."""
    parts = [f"Agent: {session.agent}", f"Branch: {session.branch}"]
    if session.prompt:
        parts.append(f"\n## Prompt\n{session.prompt}")
    if session.summary:
        parts.append(f"\n## Summary\n{session.summary}")
    if session.files_touched:
        parts.append(f"\n## Files Touched\n" + "\n".join(f"- {f}" for f in session.files_touched))
    # Store condensed transcript, not full (can be huge)
    parts.append(f"\n## Transcript (condensed)\n{_condense_transcript(session.transcript)}")
    return "\n".join(parts)


def _condense_transcript(transcript: list[dict]) -> str:
    """Condense a JSONL transcript into a readable summary for the prompt.

    Full transcripts can be very long (thousands of lines). We extract:
    - User messages (these contain the actual requests/decisions)
    - Assistant text responses (contain reasoning and choices)
    - Skip tool call details (code reads, file writes — too verbose)
    """
    parts: list[str] = []
    total_chars = 0
    char_limit = 15000  # Keep under ~4k tokens for the extraction prompt

    for entry in transcript:
        if total_chars >= char_limit:
            parts.append(f"\n... ({len(transcript) - len(parts)} more messages, truncated)")
            break

        msg_type = entry.get("type", "")
        message = entry.get("message", {})

        if msg_type == "user":
            # User messages — always include
            content = _extract_text_content(message)
            if content:
                text = f"**User:** {content}"
                parts.append(text)
                total_chars += len(text)

        elif msg_type == "assistant":
            # Assistant messages — include text, skip tool call details
            content = _extract_text_content(message)
            if content:
                # Truncate long assistant messages
                if len(content) > 500:
                    content = content[:500] + "..."
                text = f"**Assistant:** {content}"
                parts.append(text)
                total_chars += len(text)

    if not parts:
        return "(empty transcript)"

    return "\n\n".join(parts)


def _extract_text_content(message: dict) -> str:
    """Extract text content from a message, handling various formats."""
    # Direct text content
    if isinstance(message.get("content"), str):
        return message["content"]

    # Array of content blocks (Anthropic format)
    if isinstance(message.get("content"), list):
        texts = []
        for block in message["content"]:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)

    # Fall back to checking common fields
    for key in ("text", "content", "body"):
        if isinstance(message.get(key), str):
            return message[key]

    return ""


def _parse_response(
    response: anthropic.types.Message, source_id: str, session_id: str
) -> list[Decision]:
    """Parse Claude's JSON response into Decision objects."""
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

    decisions: list[Decision] = []
    for item in data.get("decisions", []):
        entities = [
            Entity(name=e["name"], entity_type=e.get("entity_type", "technology"))
            for e in item.get("entities", [])
        ]
        decisions.append(
            Decision(
                id=str(uuid.uuid4()),
                source_id=source_id,
                summary=item.get("summary", ""),
                reasoning=item.get("reasoning", ""),
                alternatives=item.get("alternatives", []),
                entities=entities,
                confidence=item.get("confidence", "medium"),
                decision_date="",  # Sessions don't have a specific decision date
                extracted_at=datetime.now(),
            )
        )
    return decisions
