"""Relevance ranking logic extracted from Context Spotlight.

Pure functions with no Streamlit dependency — suitable for testing.
"""

from __future__ import annotations

from setkontext.storage.repository import Repository
from setkontext.ui.components import CATEGORY_LABELS, build_fts_query


def expand_entities_via_graph(
    repo: Repository, direct_entities: set[str]
) -> dict[str, float]:
    """Expand entity set using relationship graph.

    Returns {entity: weight} where direct entities = 1.0, 1-hop related = 0.5.
    """
    weighted: dict[str, float] = {e: 1.0 for e in direct_entities}
    for entity in direct_entities:
        related = repo.get_related_entities(entity, depth=1)
        for rel in related:
            rel_entity = rel["entity"].lower()
            if rel_entity not in weighted:
                weighted[rel_entity] = 0.5
    return weighted


def search_and_rank(repo: Repository, task_text: str, limit: int = 10) -> list[dict]:
    """Search decisions and learnings, return ranked by relevance score.

    Each returned item has keys: type ("decision"|"learning"), score (float), data (dict).
    Uses entity relationship graph to expand search and boost related results.
    """
    fts_query = build_fts_query(task_text)
    if not fts_query:
        return []

    known_entities = {e["entity"].lower(): e for e in repo.get_entities()}
    task_entities = extract_entities_from_text(task_text, set(known_entities.keys()))

    # Expand entities via graph relationships
    expanded_entities = expand_entities_via_graph(repo, task_entities)

    decisions = repo.search_decisions(fts_query, limit=30)
    learnings = repo.search_learnings(fts_query, limit=30)

    # Also search by related entities not already in FTS results
    seen_decision_ids = {d["id"] for d in decisions}
    seen_learning_ids = {l["id"] for l in learnings}
    related_only = {e for e, w in expanded_entities.items() if w < 1.0}
    for rel_entity in related_only:
        for d in repo.get_decisions_by_entity(rel_entity):
            if d["id"] not in seen_decision_ids:
                seen_decision_ids.add(d["id"])
                decisions.append(d)
        for l in repo.get_learnings_by_entity(rel_entity):
            if l["id"] not in seen_learning_ids:
                seen_learning_ids.add(l["id"])
                learnings.append(l)

    scored: list[dict] = []

    for i, d in enumerate(decisions):
        ordinal_score = 1.0 / (1.0 + i * 0.15)
        entity_overlap = entity_overlap_score(d, task_entities)
        rel_bonus = _relationship_bonus(d, expanded_entities)
        final_score = ordinal_score * 0.6 + entity_overlap * 0.25 + rel_bonus * 0.15
        scored.append({"type": "decision", "score": final_score, "data": d})

    for i, l in enumerate(learnings):
        ordinal_score = 1.0 / (1.0 + i * 0.15)
        entity_overlap = entity_overlap_score(l, task_entities)
        rel_bonus = _relationship_bonus(l, expanded_entities)
        final_score = ordinal_score * 0.6 + entity_overlap * 0.25 + rel_bonus * 0.15
        scored.append({"type": "learning", "score": final_score, "data": l})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def _relationship_bonus(item: dict, expanded_entities: dict[str, float]) -> float:
    """Score bonus from graph-related entities (not direct matches)."""
    item_entities = {e["entity"].lower() for e in item.get("entities", [])}
    if not item_entities or not expanded_entities:
        return 0.0
    related_only = {e: w for e, w in expanded_entities.items() if w < 1.0}
    if not related_only:
        return 0.0
    matches = sum(w for e, w in related_only.items() if e in item_entities)
    return min(matches / max(len(related_only), 1), 1.0)


def extract_entities_from_text(text: str, known_entities: set[str]) -> set[str]:
    """Find known entity names that appear in the text."""
    text_lower = text.lower()
    return {e for e in known_entities if e in text_lower}


def entity_overlap_score(item: dict, task_entities: set[str]) -> float:
    """Score how many task entities appear in the item's entities."""
    if not task_entities:
        return 0.0
    item_entities = {e["entity"].lower() for e in item.get("entities", [])}
    overlap = len(item_entities & task_entities)
    return overlap / len(task_entities)


def relevance_label(score: float) -> str:
    """Return a text relevance label."""
    if score >= 0.7:
        return "high"
    elif score >= 0.4:
        return "medium"
    else:
        return "low"


def build_context_markdown(task_text: str, results: list[dict]) -> str:
    """Build a markdown context file from ranked results."""
    parts: list[str] = []
    parts.append(f"# Context for: {task_text}\n\n")

    decisions = [r for r in results if r["type"] == "decision"]
    learnings = [r for r in results if r["type"] == "learning"]

    if decisions:
        parts.append("## Relevant Decisions\n\n")
        for r in decisions:
            d = r["data"]
            parts.append(
                f"- **{d.get('summary', '')}** (confidence: {d.get('confidence', '?')})"
            )
            if d.get("reasoning"):
                reasoning = d["reasoning"]
                if len(reasoning) > 200:
                    reasoning = reasoning[:197] + "..."
                parts.append(f"\n  Why: {reasoning}")
            if d.get("source_url"):
                parts.append(f"\n  Source: {d['source_url']}")
            parts.append("\n\n")

    if learnings:
        parts.append("## Relevant Learnings\n\n")
        for r in learnings:
            l = r["data"]
            cat_label = CATEGORY_LABELS.get(l.get("category", ""), "")
            parts.append(f"- **[{cat_label}] {l.get('summary', '')}**")
            if l.get("detail"):
                detail = l["detail"]
                if len(detail) > 200:
                    detail = detail[:197] + "..."
                parts.append(f"\n  {detail}")
            parts.append("\n\n")

    parts.append("---\n*Generated by setkontext*\n")
    return "".join(parts)
