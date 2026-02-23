"""PR decision extraction using Claude.

Analyzes PR content to find implicit engineering decisions — moments where
a technical choice was made. Most PRs are routine (bug fixes, feature work
with no architectural significance) and should be skipped.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime

import anthropic

from setkontext.extraction.models import Decision, Entity, Source
from setkontext.github.fetcher import PRData

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds

EXTRACTION_PROMPT = """\
You are an engineering decision extractor. Analyze the following GitHub Pull Request \
and determine if it contains any significant engineering decisions.

A "decision" is a deliberate technical choice that affects the system's architecture, \
technology stack, design patterns, or approach. Examples:
- Choosing a database, framework, or library
- Adopting or rejecting an architectural pattern (microservices, event-driven, etc.)
- Making a tradeoff between competing concerns (performance vs. simplicity, etc.)
- Deciding on a data model or API design approach
- Choosing to take on or pay off technical debt

Most PRs do NOT contain decisions. Routine bug fixes, feature implementations that follow \
existing patterns, dependency updates, and documentation changes are NOT decisions. \
Be selective — only extract decisions that a future developer or AI agent would need \
to know about to understand why the system is built the way it is.

## PR Content

**Title:** {title}
**PR Number:** #{number}

**Description:**
{body}

**Review Comments:**
{review_comments}

**Commit Messages:**
{commit_messages}

## Instructions

Respond with a JSON object. If there are no significant decisions, return:
{{"decisions": []}}

If there ARE decisions, return:
{{"decisions": [
  {{
    "summary": "One sentence describing what was decided",
    "reasoning": "Why this decision was made, including tradeoffs considered",
    "alternatives": ["Alternative 1 that was considered or rejected", "Alternative 2"],
    "entities": [
      {{"name": "technology or concept name", "entity_type": "technology|pattern|service|library"}}
    ],
    "confidence": "high|medium|low"
  }}
]}}

Confidence levels:
- high: Decision is explicitly stated and discussed
- medium: Decision is implied by the changes and discussion
- low: Decision might be inferred but isn't clearly stated

Respond ONLY with valid JSON, no other text.
"""


def extract_pr_decisions(
    pr: PRData, repo: str, client: anthropic.Anthropic
) -> tuple[Source, list[Decision]]:
    """Analyze a single PR for engineering decisions using Claude.

    Returns a Source and list of Decisions (usually 0, sometimes 1-2).
    """
    source = Source(
        id=f"pr:{pr.number}",
        source_type="pr",
        repo=repo,
        url=pr.url,
        title=pr.title,
        raw_content=_build_pr_text(pr),
        fetched_at=datetime.now(),
    )

    prompt = EXTRACTION_PROMPT.format(
        title=pr.title,
        number=pr.number,
        body=pr.body or "(no description)",
        review_comments=_format_comments(pr.review_comments),
        commit_messages=_format_commits(pr.commit_messages),
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Rate limited on PR #{pr.number}, retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"Rate limited on PR #{pr.number} after {MAX_RETRIES} retries, skipping")
                return source, []
        except anthropic.APIError as e:
            logger.error(f"API error analyzing PR #{pr.number}: {e}")
            return source, []

    decisions = _parse_response(response, source.id, pr.merged_at)
    return source, decisions


def extract_pr_decisions_batch(
    prs: list[PRData], repo: str, client: anthropic.Anthropic
) -> list[tuple[Source, list[Decision]]]:
    """Extract decisions from multiple PRs.

    Processes PRs individually (batching into single prompts risks quality).
    """
    results: list[tuple[Source, list[Decision]]] = []
    for pr in prs:
        result = extract_pr_decisions(pr, repo, client)
        results.append(result)
    return results


def _build_pr_text(pr: PRData) -> str:
    """Build the full text representation of a PR for storage."""
    parts = [f"# {pr.title}\n"]
    if pr.body:
        parts.append(pr.body)
    if pr.review_comments:
        parts.append("\n## Review Comments\n")
        parts.extend(f"- {c}" for c in pr.review_comments[:10])
    return "\n".join(parts)


def _format_comments(comments: list[str]) -> str:
    if not comments:
        return "(no review comments)"
    # Limit total text to avoid huge prompts
    formatted: list[str] = []
    total_chars = 0
    for comment in comments:
        if total_chars > 3000:
            formatted.append(f"... ({len(comments) - len(formatted)} more comments)")
            break
        formatted.append(f"- {comment}")
        total_chars += len(comment)
    return "\n".join(formatted)


def _format_commits(messages: list[str]) -> str:
    if not messages:
        return "(no commit messages)"
    return "\n".join(f"- {msg}" for msg in messages[:10])


def _parse_response(
    response: anthropic.types.Message, source_id: str, decision_date: str
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
                decision_date=decision_date,
                extracted_at=datetime.now(),
            )
        )
    return decisions
