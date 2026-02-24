"""Decision validator: proposed approach → conflict detection → structured verdict.

Takes a proposed implementation approach, finds all potentially relevant decisions,
and uses Claude to determine whether the approach conflicts with, aligns with, or
is not covered by existing engineering decisions.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field

import anthropic

from setkontext.storage.repository import Repository

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds

VALIDATION_PROMPT = """\
You are a strict engineering decision validator. Your job is to check whether a \
proposed implementation approach CONFLICTS with the team's existing engineering decisions.

Err on the side of flagging potential conflicts — it's better to warn about a possible \
issue than to let a contradiction slip through.

## Proposed Approach
{proposed_approach}

{context_section}

## Team's Engineering Decisions
{decisions_text}

## Instructions

Analyze the proposed approach against EVERY decision listed above. For each decision, \
determine if the proposal:
- **CONFLICTS** with it (directly contradicts an explicit choice)
- **ALIGNS** with it (consistent with or supported by the decision)
- Is **IRRELEVANT** (decision is about a different topic)

Then produce your overall verdict.

Respond with ONLY valid JSON in this exact format:
{{
  "verdict": "CONFLICTS" | "ALIGNS" | "NO_COVERAGE",
  "conflicts": [
    {{
      "decision_summary": "The specific decision that is violated",
      "source_url": "URL of the source (from the decisions above)",
      "explanation": "Why the proposed approach conflicts with this decision",
      "severity": "hard" | "soft"
    }}
  ],
  "alignments": [
    "Brief description of each decision that supports the approach"
  ],
  "warnings": [
    "Soft concerns even if no hard conflict (e.g., team pattern not formally decided but consistently used)"
  ],
  "recommendation": "One clear, actionable sentence telling the agent what to do"
}}

Verdict rules:
- **CONFLICTS**: At least one hard conflict exists (explicit decision contradicted)
- **ALIGNS**: No conflicts, and at least one decision actively supports the approach
- **NO_COVERAGE**: No relevant decisions exist for this topic — the team hasn't decided on this yet

Severity rules:
- **hard**: The team explicitly decided on an alternative (e.g., "chose PostgreSQL" but agent proposes MongoDB)
- **soft**: No explicit decision, but the team has a consistent pattern (e.g., REST everywhere, agent proposes GraphQL)

The recommendation must be specific and actionable:
- GOOD: "Use PostgreSQL instead — the team chose it over MongoDB for X reasons (see PR #42)"
- BAD: "There might be a conflict, please review"

If verdict is NO_COVERAGE, the recommendation should note that this is a new decision area \
and suggest documenting whatever choice is made.
"""


@dataclass
class ConflictDetail:
    decision_summary: str
    source_url: str
    explanation: str
    severity: str  # "hard" | "soft"


@dataclass
class ValidationResult:
    proposed_approach: str
    verdict: str  # "CONFLICTS" | "ALIGNS" | "NO_COVERAGE"
    conflicts: list[ConflictDetail] = field(default_factory=list)
    alignments: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendation: str = ""
    decisions_checked: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


class DecisionValidator:
    """Validates proposed approaches against existing engineering decisions."""

    def __init__(self, repo: Repository, anthropic_client: anthropic.Anthropic) -> None:
        self._repo = repo
        self._client = anthropic_client

    def validate(self, proposed_approach: str, context: str = "") -> ValidationResult:
        """Check a proposed approach against stored decisions."""
        decisions = self._find_relevant_decisions(proposed_approach)

        if not decisions:
            return ValidationResult(
                proposed_approach=proposed_approach,
                verdict="NO_COVERAGE",
                recommendation=(
                    "No engineering decisions exist for this area. "
                    "Proceed with your best judgment, but consider documenting "
                    "this choice as a new decision for the team."
                ),
                decisions_checked=0,
            )

        return self._run_validation(proposed_approach, context, decisions)

    def _find_relevant_decisions(self, proposed_approach: str) -> list[dict]:
        """Find decisions relevant to the proposed approach.

        Uses the same FTS + entity matching strategy as QueryEngine,
        but casts a wider net since we want to catch all potential conflicts.
        """
        seen_ids: set[str] = set()
        results: list[dict] = []

        # Strategy 1: Full-text search
        fts_query = self._build_fts_query(proposed_approach)
        if fts_query:
            for d in self._repo.search_decisions(fts_query, limit=15):
                if d["id"] not in seen_ids:
                    seen_ids.add(d["id"])
                    results.append(d)

        # Strategy 2: Entity matching
        entities = self._extract_entities(proposed_approach)
        for entity in entities:
            for d in self._repo.get_decisions_by_entity(entity):
                if d["id"] not in seen_ids:
                    seen_ids.add(d["id"])
                    results.append(d)

        # Strategy 3: If very few results, broaden to all decisions
        if len(results) < 3:
            for d in self._repo.get_all_decisions(limit=15):
                if d["id"] not in seen_ids:
                    seen_ids.add(d["id"])
                    results.append(d)

        return results[:20]  # Wider net than query engine (20 vs 15)

    def _build_fts_query(self, text: str) -> str:
        """Convert approach text into an FTS5 query."""
        stop_words = {
            "i", "plan", "to", "will", "am", "going", "want", "need",
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "do", "does", "did", "have", "has", "had", "this", "that",
            "for", "with", "from", "about", "use", "using", "add",
            "new", "create", "build", "implement", "make", "and", "or",
            "but", "in", "on", "of", "it", "its", "we", "our", "not",
        }

        words = []
        for word in text.lower().split():
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned and cleaned not in stop_words and len(cleaned) > 2:
                words.append(cleaned)

        return " OR ".join(words) if words else ""

    def _extract_entities(self, text: str) -> list[str]:
        """Find known entity names in the proposed approach."""
        text_lower = text.lower()
        known_entities = [e["entity"] for e in self._repo.get_entities()]
        return [e for e in known_entities if e.lower() in text_lower]

    def _run_validation(
        self, proposed_approach: str, context: str, decisions: list[dict]
    ) -> ValidationResult:
        """Use Claude to validate the approach against decisions."""
        decisions_text = self._format_decisions(decisions)

        context_section = ""
        if context:
            context_section = f"## Context\n{context}"

        prompt = VALIDATION_PROMPT.format(
            proposed_approach=proposed_approach,
            context_section=context_section,
            decisions_text=decisions_text,
        )

        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                break
            except anthropic.RateLimitError:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"Rate limited on validation, retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    return ValidationResult(
                        proposed_approach=proposed_approach,
                        verdict="NO_COVERAGE",
                        recommendation="Unable to validate: API rate limit exceeded. Try again later.",
                        decisions_checked=len(decisions),
                    )
            except anthropic.APIError as e:
                logger.error(f"API error during validation: {e}")
                return ValidationResult(
                    proposed_approach=proposed_approach,
                    verdict="NO_COVERAGE",
                    recommendation=f"Unable to validate due to API error: {e}",
                    decisions_checked=len(decisions),
                )

        if not response.content:
            return ValidationResult(
                proposed_approach=proposed_approach,
                verdict="NO_COVERAGE",
                recommendation="No response from API.",
                decisions_checked=len(decisions),
            )

        return self._parse_response(
            response.content[0].text.strip(), proposed_approach, len(decisions)
        )

    def _parse_response(
        self, text: str, proposed_approach: str, decisions_checked: int
    ) -> ValidationResult:
        """Parse Claude's JSON response into a ValidationResult."""
        # Handle markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse validation JSON: {text[:200]}")
            return ValidationResult(
                proposed_approach=proposed_approach,
                verdict="NO_COVERAGE",
                recommendation="Validation response was not parseable. Proceed with caution.",
                decisions_checked=decisions_checked,
            )

        conflicts = [
            ConflictDetail(
                decision_summary=c.get("decision_summary", ""),
                source_url=c.get("source_url", ""),
                explanation=c.get("explanation", ""),
                severity=c.get("severity", "soft"),
            )
            for c in data.get("conflicts", [])
        ]

        return ValidationResult(
            proposed_approach=proposed_approach,
            verdict=data.get("verdict", "NO_COVERAGE"),
            conflicts=conflicts,
            alignments=data.get("alignments", []),
            warnings=data.get("warnings", []),
            recommendation=data.get("recommendation", ""),
            decisions_checked=decisions_checked,
        )

    def _format_decisions(self, decisions: list[dict]) -> str:
        """Format decisions for the validation prompt."""
        parts: list[str] = []
        for i, d in enumerate(decisions, 1):
            source_type = d.get("source_type", "unknown")
            source_url = d.get("source_url", "")
            parts.append(f"### Decision {i} (from {source_type}, confidence: {d.get('confidence', 'unknown')})")
            parts.append(f"**Summary:** {d.get('summary', '')}")
            if d.get("reasoning"):
                parts.append(f"**Reasoning:** {d['reasoning']}")
            if d.get("alternatives"):
                alts = d["alternatives"]
                if isinstance(alts, list) and alts:
                    parts.append(f"**Rejected alternatives:** {', '.join(alts)}")
            parts.append(f"**Source:** {source_url}")
            parts.append("")
        return "\n".join(parts)
