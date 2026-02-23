"""Query engine: question → relevant decisions → synthesized answer.

Takes a natural language question, finds relevant decisions via FTS and entity
matching, then uses Claude to synthesize a coherent answer with source links.
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

SYNTHESIS_PROMPT = """\
You are a senior engineering advisor for a software team. You have access to the team's \
documented engineering decisions extracted from their codebase, PRs, ADRs, and documentation.

Your job is to answer questions in a way that helps the person (or AI agent) make the \
RIGHT implementation choice — one that's consistent with the team's existing decisions.

## Question
{question}

## Team's Engineering Decisions
{decisions_text}

## Instructions

Determine the type of question and respond accordingly:

**If it's a "why" question** (why did we choose X?):
- Explain the decision, reasoning, and what alternatives were rejected
- Reference specific sources

**If it's a "how should I" question** (how should I add caching / build a new endpoint / etc.):
- Frame existing decisions as CONSTRAINTS and GUIDELINES for the implementation
- Be specific: "Use FastAPI for the endpoint, PostgreSQL for storage, and follow the dependency injection pattern for auth" — not vague generalities
- Warn about approaches that would CONTRADICT existing decisions
- If the team rejected an alternative, explain why so the person doesn't re-propose it

**If it's a "what" question** (what database do we use? what's the architecture?):
- Provide a clear, factual summary from the decisions

**For all responses:**
- Be direct and actionable — this output may be consumed by an AI coding agent
- Reference source links so decisions can be verified
- If decisions don't cover the topic, say so clearly — don't make up guidance
- If decisions contradict each other, note the conflict and which is more recent
"""


@dataclass
class QueryResult:
    question: str
    answer: str
    decisions: list[dict] = field(default_factory=list)
    sources_searched: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def to_text(self) -> str:
        lines = [self.answer, ""]
        if self.decisions:
            lines.append("Sources:")
            for d in self.decisions:
                source_url = d.get("source_url", "")
                summary = d.get("summary", "")
                confidence = d.get("confidence", "")
                lines.append(f"  - [{confidence}] {summary}")
                if source_url:
                    lines.append(f"    {source_url}")
        return "\n".join(lines)


class QueryEngine:
    """Finds relevant decisions and synthesizes answers."""

    def __init__(self, repo: Repository, anthropic_client: anthropic.Anthropic) -> None:
        self._repo = repo
        self._client = anthropic_client

    def query(self, question: str) -> QueryResult:
        """Answer a question using stored decisions."""
        # Step 1: Find relevant decisions via multiple strategies
        decisions = self._find_relevant_decisions(question)

        if not decisions:
            return QueryResult(
                question=question,
                answer="No relevant engineering decisions found for this question. "
                "The repository may not have decisions related to this topic, "
                "or extraction hasn't been run yet.",
                decisions=[],
                sources_searched=0,
            )

        # Step 2: Synthesize answer using Claude
        answer = self._synthesize_answer(question, decisions)

        return QueryResult(
            question=question,
            answer=answer,
            decisions=decisions,
            sources_searched=len(decisions),
        )

    def _find_relevant_decisions(self, question: str) -> list[dict]:
        """Find decisions relevant to the question using FTS and entity matching."""
        seen_ids: set[str] = set()
        results: list[dict] = []

        # Strategy 1: Full-text search
        fts_query = self._build_fts_query(question)
        if fts_query:
            for d in self._repo.search_decisions(fts_query, limit=10):
                if d["id"] not in seen_ids:
                    seen_ids.add(d["id"])
                    results.append(d)

        # Strategy 2: Entity matching — extract likely entity names from the question
        entities = self._extract_query_entities(question)
        for entity in entities:
            for d in self._repo.get_decisions_by_entity(entity):
                if d["id"] not in seen_ids:
                    seen_ids.add(d["id"])
                    results.append(d)

        # Strategy 3: If nothing found, fall back to getting all decisions (limited)
        if not results:
            results = self._repo.get_all_decisions(limit=10)

        return results[:15]  # Cap at 15 to keep the synthesis prompt manageable

    def _build_fts_query(self, question: str) -> str:
        """Convert a natural language question into an FTS5 query.

        Simple approach: extract meaningful words, join with OR.
        """
        stop_words = {
            "why", "did", "we", "the", "a", "an", "is", "are", "was", "were",
            "do", "does", "how", "what", "when", "where", "which", "who",
            "our", "their", "this", "that", "for", "with", "from", "about",
            "use", "using", "used", "choose", "chose", "chosen", "pick",
            "picked", "decide", "decided", "should", "would", "could",
            "have", "has", "had", "not", "and", "or", "but", "in", "on",
            "to", "of", "it", "its", "be", "been", "being",
        }

        words = []
        for word in question.lower().split():
            # Strip punctuation
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned and cleaned not in stop_words and len(cleaned) > 2:
                words.append(cleaned)

        if not words:
            return ""

        return " OR ".join(words)

    def _extract_query_entities(self, question: str) -> list[str]:
        """Extract potential entity names from a question.

        Simple heuristic: look for known technology/pattern terms.
        """
        question_lower = question.lower()
        known_entities = [e["entity"] for e in self._repo.get_entities()]
        return [e for e in known_entities if e in question_lower]

    def _synthesize_answer(self, question: str, decisions: list[dict]) -> str:
        """Use Claude to synthesize a coherent answer from relevant decisions."""
        decisions_text = self._format_decisions_for_prompt(decisions)

        prompt = SYNTHESIS_PROMPT.format(
            question=question,
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
                    logger.warning(f"Rate limited on query, retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    return "Unable to synthesize answer: API rate limit exceeded. Try again later."
            except anthropic.APIError as e:
                logger.error(f"API error during query synthesis: {e}")
                return f"Unable to synthesize answer due to an API error: {e}"

        if not response.content:
            return "No response from API."

        return response.content[0].text.strip()

    def _format_decisions_for_prompt(self, decisions: list[dict]) -> str:
        """Format decisions for inclusion in the synthesis prompt."""
        parts: list[str] = []
        for i, d in enumerate(decisions, 1):
            source_type = d.get("source_type", "unknown")
            source_url = d.get("source_url", "")
            parts.append(f"### Decision {i} (from {source_type})")
            parts.append(f"**Summary:** {d.get('summary', '')}")
            if d.get("reasoning"):
                parts.append(f"**Reasoning:** {d['reasoning']}")
            if d.get("alternatives"):
                alts = d["alternatives"]
                if isinstance(alts, list):
                    parts.append(f"**Alternatives considered:** {', '.join(alts)}")
            parts.append(f"**Confidence:** {d.get('confidence', 'unknown')}")
            parts.append(f"**Source:** {source_url}")
            parts.append("")
        return "\n".join(parts)
