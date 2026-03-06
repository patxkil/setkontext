"""Consolidation: promote recurring learnings into decisions.

Analyzes clusters of learnings (grouped by shared entities) and synthesizes
them into Decision objects when a pattern emerges. This bridges the gap
between session-level memory (learnings) and project-level memory (decisions).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import anthropic

from setkontext.extraction.models import Decision, Entity, Source

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0
MAX_TOKENS = 2048


@dataclass
class ConsolidationProposal:
    """A proposed decision synthesized from multiple learnings."""
    decision: Decision
    source_learning_ids: list[str] = field(default_factory=list)
    rationale: str = ""  # Why this cluster warrants a decision


CONSOLIDATION_PROMPT = """\
You are an engineering decision analyst. You're reviewing a cluster of learnings \
from AI coding sessions that all relate to the same technology/pattern: **{entity}**.

Your job: determine if these learnings collectively represent an **engineering decision** \
that should be documented. Not every cluster warrants a decision — only promote when \
there's a clear pattern, convention, or architectural choice that future developers \
(or AI agents) should know about.

## What qualifies as a decision?
- A recurring pattern that the team has settled on (even if never explicitly decided)
- A gotcha that's been hit multiple times, implying a convention should be established
- An implementation approach that's become the standard way of doing things
- A technology choice that's been validated through experience

## What does NOT qualify?
- One-off bug fixes with no broader implication
- Implementation details that are obvious from reading the code
- Learnings that contradict each other (signal an unresolved question, not a decision)

## Learnings Cluster ({learning_count} learnings about "{entity}")

{learnings_text}

## Instructions

Analyze these learnings and determine if they collectively represent one or more \
engineering decisions. For each proposed decision, provide:

Respond with a JSON object:
{{"proposals": [
  {{
    "summary": "One sentence: what the team has decided or established",
    "reasoning": "Why this is a decision, citing the learnings that support it",
    "alternatives": ["What else could have been done instead"],
    "entities": [
      {{"name": "technology or concept", "entity_type": "technology|pattern|service|library"}}
    ],
    "confidence": "high|medium",
    "source_learning_ids": ["ids of learnings that support this decision"],
    "rationale": "Why these learnings warrant being promoted to a decision"
  }}
]}}

If the learnings do NOT warrant any decisions (too scattered, contradictory, or trivial), \
return {{"proposals": []}}.

Respond ONLY with valid JSON, no other text.
"""


def find_consolidation_proposals(
    clusters: list[dict],
    client: anthropic.Anthropic,
) -> list[ConsolidationProposal]:
    """Analyze learning clusters and propose decisions.

    Args:
        clusters: Output of Repository.get_learning_clusters().
        client: Anthropic API client.

    Returns:
        List of proposed decisions with source learning references.
    """
    all_proposals: list[ConsolidationProposal] = []

    for cluster in clusters:
        entity = cluster["entity"]
        learnings = cluster["learnings"]

        if not learnings:
            continue

        proposals = _analyze_cluster(entity, learnings, client)
        all_proposals.extend(proposals)

    return all_proposals


def _analyze_cluster(
    entity: str,
    learnings: list[dict],
    client: anthropic.Anthropic,
) -> list[ConsolidationProposal]:
    """Send a single cluster to Claude for analysis."""
    learnings_text = _format_learnings(learnings)

    prompt = CONSOLIDATION_PROMPT.format(
        entity=entity,
        learning_count=len(learnings),
        learnings_text=learnings_text,
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
                logger.error("Rate limited after retries, skipping cluster")
                return []
        except anthropic.APIError as e:
            logger.error(f"API error during consolidation: {e}")
            return []

    return _parse_response(response, entity)


def _format_learnings(learnings: list[dict]) -> str:
    """Format learnings for the prompt."""
    parts: list[str] = []
    for i, l in enumerate(learnings, 1):
        category = l.get("category", "unknown").replace("_", " ").upper()
        parts.append(
            f"### Learning {i} [{category}] (id: {l['id']})\n"
            f"**Summary:** {l.get('summary', '')}\n"
            f"**Detail:** {l.get('detail', '')}\n"
            f"**Components:** {', '.join(l.get('components', []))}\n"
            f"**Date:** {l.get('session_date', 'unknown')}"
        )
    return "\n\n".join(parts)


def _parse_response(
    response: anthropic.types.Message, entity: str
) -> list[ConsolidationProposal]:
    """Parse Claude's response into ConsolidationProposal objects."""
    if not response.content:
        return []

    text = response.content[0].text.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse consolidation JSON for {entity}: {text[:200]}")
        return []

    proposals: list[ConsolidationProposal] = []
    now = datetime.now()

    for item in data.get("proposals", []):
        entities = [
            Entity(name=e["name"], entity_type=e.get("entity_type", "technology"))
            for e in item.get("entities", [])
        ]

        source_learning_ids = item.get("source_learning_ids", [])
        source_id = f"consolidation:{uuid.uuid4().hex[:12]}"

        decision = Decision(
            id=str(uuid.uuid4()),
            source_id=source_id,
            summary=item.get("summary", ""),
            reasoning=item.get("reasoning", ""),
            alternatives=item.get("alternatives", []),
            entities=entities,
            confidence=item.get("confidence", "medium"),
            decision_date=now.strftime("%Y-%m-%d"),
            extracted_at=now,
        )

        proposals.append(ConsolidationProposal(
            decision=decision,
            source_learning_ids=source_learning_ids,
            rationale=item.get("rationale", ""),
        ))

    return proposals


def create_consolidation_source(
    proposal: ConsolidationProposal,
    repo: str,
) -> Source:
    """Create a Source record for a consolidated decision."""
    learning_refs = ", ".join(proposal.source_learning_ids[:5])
    return Source(
        id=proposal.decision.source_id,
        source_type="consolidation",
        repo=repo,
        url="",
        title=f"[consolidated] {proposal.decision.summary[:80]}",
        raw_content=(
            f"Consolidated from {len(proposal.source_learning_ids)} learnings: "
            f"{learning_refs}\n\nRationale: {proposal.rationale}"
        ),
        fetched_at=datetime.now(),
    )
