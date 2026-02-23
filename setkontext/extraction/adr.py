"""ADR (Architecture Decision Record) extraction.

Parses ADR markdown files into Decision objects. Handles two common formats:
- Nygard format: Status, Context, Decision, Consequences sections
- MADR format: similar structure with slightly different headings

Falls back to LLM extraction for non-standard formats.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from setkontext.extraction.models import Decision, Entity, Source
from setkontext.github.fetcher import ADRData

# Patterns for section headings in ADR files
SECTION_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "status": [re.compile(r"^##\s*Status\s*$", re.IGNORECASE | re.MULTILINE)],
    "context": [
        re.compile(r"^##\s*Context(?:\s+and\s+Problem\s+Statement)?\s*$", re.IGNORECASE | re.MULTILINE),
    ],
    "decision": [
        re.compile(r"^##\s*Decision(?:\s+Outcome)?\s*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^##\s*Chosen\s+Option\s*$", re.IGNORECASE | re.MULTILINE),
    ],
    "consequences": [
        re.compile(r"^##\s*Consequences\s*$", re.IGNORECASE | re.MULTILINE),
    ],
    "alternatives": [
        re.compile(r"^##\s*(?:Considered\s+)?Options?\s*$", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^##\s*Alternatives(?:\s+Considered)?\s*$", re.IGNORECASE | re.MULTILINE),
    ],
}


def extract_adr_decisions(adr: ADRData, repo: str) -> tuple[Source, list[Decision]]:
    """Parse an ADR file and extract decisions.

    Returns a Source and list of Decisions (usually 0 or 1).
    """
    source = Source(
        id=f"adr:{adr.path}",
        source_type="adr",
        repo=repo,
        url=adr.url,
        title=_extract_title(adr.content),
        raw_content=adr.content,
        fetched_at=datetime.now(),
    )

    sections = _parse_sections(adr.content)

    # Need at least a decision or context section to extract anything useful
    if not sections.get("decision") and not sections.get("context"):
        return source, []

    summary = _build_summary(sections, source.title)
    reasoning = sections.get("context", "")
    alternatives = _extract_alternatives(sections.get("alternatives", ""))
    entities = _extract_entities_from_text(
        f"{summary} {reasoning} {sections.get('alternatives', '')}"
    )
    confidence = _assess_confidence(sections)

    decision = Decision(
        id=str(uuid.uuid4()),
        source_id=source.id,
        summary=summary,
        reasoning=reasoning,
        alternatives=alternatives,
        entities=entities,
        confidence=confidence,
        decision_date=_extract_date(adr.content),
        extracted_at=datetime.now(),
    )

    return source, [decision]


def _extract_title(content: str) -> str:
    """Extract the H1 title from ADR content."""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        # Strip common prefixes like "ADR-001:" or "1."
        title = match.group(1).strip()
        title = re.sub(r"^(?:ADR[-\s]*\d+[:\s]*|[\d]+\.\s*)", "", title)
        return title.strip()
    # Fallback: first non-empty line
    for line in content.splitlines():
        line = line.strip()
        if line:
            return line
    return "Untitled ADR"


def _parse_sections(content: str) -> dict[str, str]:
    """Parse ADR content into named sections based on headings."""
    sections: dict[str, str] = {}

    # Find all H2 headings and their positions
    heading_positions: list[tuple[str, int, int]] = []
    for section_name, patterns in SECTION_PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(content):
                heading_positions.append((section_name, match.start(), match.end()))

    if not heading_positions:
        return sections

    # Sort by position in document
    heading_positions.sort(key=lambda x: x[1])

    # Extract text between headings
    for i, (name, _start, end) in enumerate(heading_positions):
        if i + 1 < len(heading_positions):
            next_start = heading_positions[i + 1][1]
            section_text = content[end:next_start].strip()
        else:
            section_text = content[end:].strip()

        # Only keep the first occurrence of each section type
        if name not in sections:
            sections[name] = section_text

    return sections


def _build_summary(sections: dict[str, str], title: str) -> str:
    """Build a decision summary from parsed sections."""
    decision_text = sections.get("decision", "")
    if decision_text:
        # Take the first paragraph or first 300 chars
        first_para = decision_text.split("\n\n")[0].strip()
        if len(first_para) <= 300:
            return first_para
        return first_para[:297] + "..."

    # Fall back to the title if no decision section
    return title


def _extract_alternatives(text: str) -> list[str]:
    """Extract alternative options from the alternatives/options section."""
    if not text:
        return []

    alternatives: list[str] = []

    # Look for list items (- or * or numbered)
    for match in re.finditer(r"^[\s]*(?:[-*]|\d+\.)\s+(.+)$", text, re.MULTILINE):
        item = match.group(1).strip()
        if item:
            alternatives.append(item)

    return alternatives


def _extract_entities_from_text(text: str) -> list[Entity]:
    """Extract technology/pattern entities from text using simple heuristics.

    This is intentionally simple. The PR extractor uses LLM for richer extraction.
    For ADRs, the structured format gives us enough signal with basic matching.
    """
    text_lower = text.lower()
    entities: list[Entity] = []
    seen: set[str] = set()

    # Technology keywords to look for
    tech_keywords = {
        "postgresql": "technology", "postgres": "technology", "mysql": "technology",
        "mongodb": "technology", "sqlite": "technology", "redis": "technology",
        "elasticsearch": "technology", "dynamodb": "technology", "cassandra": "technology",
        "react": "technology", "vue": "technology", "angular": "technology",
        "svelte": "technology", "next.js": "technology", "nextjs": "technology",
        "django": "technology", "flask": "technology", "fastapi": "technology",
        "express": "technology", "spring": "technology", "rails": "technology",
        "docker": "technology", "kubernetes": "technology", "k8s": "technology",
        "terraform": "technology", "aws": "technology", "gcp": "technology",
        "azure": "technology", "graphql": "technology", "grpc": "technology",
        "rest": "technology", "kafka": "technology", "rabbitmq": "technology",
        "typescript": "technology", "python": "technology", "java": "technology",
        "go": "technology", "rust": "technology", "node.js": "technology",
        "nodejs": "technology",
    }

    pattern_keywords = {
        "microservice": "pattern", "monolith": "pattern", "serverless": "pattern",
        "event-driven": "pattern", "cqrs": "pattern", "event sourcing": "pattern",
        "saga": "pattern", "circuit breaker": "pattern", "api gateway": "pattern",
        "pub/sub": "pattern", "message queue": "pattern",
    }

    for keyword, etype in {**tech_keywords, **pattern_keywords}.items():
        # Use word boundary matching to avoid false positives (e.g. "go" in "MongoDB")
        pattern = r"\b" + re.escape(keyword) + r"\b"
        if re.search(pattern, text_lower) and keyword not in seen:
            seen.add(keyword)
            entities.append(Entity(name=keyword, entity_type=etype))

    return entities


def _assess_confidence(sections: dict[str, str]) -> str:
    """Assess confidence level based on how well-structured the ADR is."""
    has_decision = bool(sections.get("decision"))
    has_context = bool(sections.get("context"))
    has_alternatives = bool(sections.get("alternatives"))

    if has_decision and has_context and has_alternatives:
        return "high"
    if has_decision and has_context:
        return "high"
    if has_decision or has_context:
        return "medium"
    return "low"


def _extract_date(content: str) -> str:
    """Try to extract a date from ADR content."""
    # Common patterns: "Date: 2024-01-15" or "2024-01-15"
    date_pattern = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
    match = date_pattern.search(content)
    if match:
        return match.group(1)
    return ""
