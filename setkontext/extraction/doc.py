"""General documentation decision extraction using Claude.

For markdown docs that aren't formal ADRs (e.g. ARCHITECTURE.md, PRODUCT_STRATEGY.md).
These contain decisions but in unstructured form — Claude extracts them.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime

import anthropic

from setkontext.extraction.models import Decision, Entity, Source
from setkontext.github.fetcher import ADRData

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds

EXTRACTION_PROMPT = """\
You are an engineering decision extractor. Analyze the following documentation file \
from a software project and extract any significant engineering or product decisions.

A "decision" is a deliberate choice that affects the system's architecture, \
technology stack, design patterns, strategy, or approach. Examples:
- Choosing a specific technology (database, framework, language, cloud provider)
- Adopting an architectural pattern (monolith, microservices, event-driven)
- Defining a product strategy or phased approach
- Making a tradeoff between competing concerns
- Defining data models or API design approaches
- Choosing between build vs. buy

Extract EACH distinct decision separately. A single document may contain many decisions.

## Document

**File:** {path}

**Content:**
{content}

## Instructions

Respond with a JSON object:
{{"decisions": [
  {{
    "summary": "One sentence describing what was decided",
    "reasoning": "Why this decision was made, including tradeoffs",
    "alternatives": ["Alternative that was considered or rejected"],
    "entities": [
      {{"name": "technology or concept name", "entity_type": "technology|pattern|service|library"}}
    ],
    "confidence": "high|medium|low"
  }}
]}}

If the document contains no engineering decisions, return {{"decisions": []}}.

Be thorough — a strategy document or architecture doc may contain 5-10+ distinct decisions.
Respond ONLY with valid JSON, no other text.
"""


def extract_doc_decisions(
    doc: ADRData, repo: str, client: anthropic.Anthropic
) -> tuple[Source, list[Decision]]:
    """Analyze a documentation file for engineering decisions using Claude.

    For docs that are too long, we truncate to avoid hitting token limits.
    """
    source = Source(
        id=f"doc:{doc.path}",
        source_type="doc",
        repo=repo,
        url=doc.url,
        title=_extract_title(doc.content, doc.path),
        raw_content=doc.content,
        fetched_at=datetime.now(),
    )

    # Truncate very long docs to ~12k chars (fits comfortably in context)
    content = doc.content
    if len(content) > 12000:
        content = content[:12000] + "\n\n[... truncated ...]"

    prompt = EXTRACTION_PROMPT.format(path=doc.path, content=content)

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"Rate limited on {doc.path}, retrying in {delay}s...")
                time.sleep(delay)
            else:
                logger.error(f"Rate limited on {doc.path} after {MAX_RETRIES} retries, skipping")
                return source, []
        except anthropic.APIError as e:
            logger.error(f"API error analyzing {doc.path}: {e}")
            return source, []

    decisions = _parse_response(response, source.id)
    return source, decisions


def _extract_title(content: str, path: str) -> str:
    """Extract the H1 title or fall back to the filename."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    # Fall back to filename
    return path.split("/")[-1].replace(".md", "").replace("-", " ").title()


def _parse_response(
    response: anthropic.types.Message, source_id: str
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
                decision_date="",
                extracted_at=datetime.now(),
            )
        )
    return decisions
