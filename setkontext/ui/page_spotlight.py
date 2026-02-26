"""Context Spotlight page — task-scoped relevance ranking."""

from __future__ import annotations

import streamlit as st

from setkontext.config import Config
from setkontext.storage.repository import Repository
from setkontext.ui.components import (
    CATEGORY_LABELS,
    build_fts_query,
    category_badge,
    check_db_exists,
    confidence_badge,
)


def render(get_repo) -> None:
    """Render the context spotlight page."""
    st.header("Context Spotlight")
    st.caption("Describe your task and see which decisions and learnings are most relevant.")

    config = Config.load()
    if not check_db_exists(config):
        return

    repo = get_repo()

    task_text = st.text_area(
        "What are you working on?",
        placeholder="e.g., Add a caching layer for the user API, Fix the authentication timeout...",
        key="spotlight_task",
    )

    if st.button("Find relevant context", type="primary") and task_text.strip():
        results = _search_and_rank(repo, task_text)

        if not results:
            st.info("No relevant decisions or learnings found for this task.")
            return

        st.subheader(f"Found {len(results)} relevant items")

        # Render ranked results
        for item in results:
            _render_ranked_item(item)

        # Copy as context
        st.divider()
        context_md = _build_context_markdown(task_text, results)
        st.download_button(
            "Download as context file",
            data=context_md,
            file_name="context.md",
            mime="text/markdown",
        )

        with st.expander("Preview context output"):
            st.code(context_md, language="markdown")


def _search_and_rank(repo: Repository, task_text: str) -> list[dict]:
    """Search decisions and learnings, rank by relevance."""
    fts_query = build_fts_query(task_text)
    if not fts_query:
        return []

    # Get known entities for overlap scoring
    known_entities = {e["entity"].lower(): e for e in repo.get_entities()}
    task_entities = _extract_entities_from_text(task_text, set(known_entities.keys()))

    # Search decisions
    decisions = repo.search_decisions(fts_query, limit=30)
    # Search learnings
    learnings = repo.search_learnings(fts_query, limit=30)

    scored: list[dict] = []

    # Score decisions (ordinal position-based + entity overlap)
    for i, d in enumerate(decisions):
        ordinal_score = 1.0 / (1.0 + i * 0.15)  # Decays with position
        entity_overlap = _entity_overlap_score(d, task_entities)
        final_score = ordinal_score * 0.7 + entity_overlap * 0.3
        scored.append({
            "type": "decision",
            "score": final_score,
            "data": d,
        })

    # Score learnings
    for i, l in enumerate(learnings):
        ordinal_score = 1.0 / (1.0 + i * 0.15)
        entity_overlap = _entity_overlap_score(l, task_entities)
        final_score = ordinal_score * 0.7 + entity_overlap * 0.3
        scored.append({
            "type": "learning",
            "score": final_score,
            "data": l,
        })

    # Sort by score descending, take top 20
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:20]


def _extract_entities_from_text(text: str, known_entities: set[str]) -> set[str]:
    """Find known entity names that appear in the text."""
    text_lower = text.lower()
    return {e for e in known_entities if e in text_lower}


def _entity_overlap_score(item: dict, task_entities: set[str]) -> float:
    """Score how many task entities appear in the item's entities."""
    if not task_entities:
        return 0.0
    item_entities = {
        e["entity"].lower() for e in item.get("entities", [])
    }
    overlap = len(item_entities & task_entities)
    return overlap / len(task_entities)


def _relevance_indicator(score: float) -> str:
    """Return a visual relevance indicator."""
    if score >= 0.7:
        return "\U0001f7e2 High"
    elif score >= 0.4:
        return "\U0001f7e1 Medium"
    else:
        return "\u26aa Low"


def _render_ranked_item(item: dict) -> None:
    """Render a single ranked result."""
    data = item["data"]
    score = item["score"]
    item_type = item["type"]
    relevance = _relevance_indicator(score)

    if item_type == "decision":
        badge = confidence_badge(data.get("confidence", ""))
        summary = data.get("summary", "Untitled")
        label = f"{relevance} | {badge} **Decision:** {summary}"

        with st.expander(label):
            if data.get("reasoning"):
                st.markdown(f"**Reasoning:** {data['reasoning']}")
            if data.get("alternatives"):
                alts = data["alternatives"]
                if isinstance(alts, list) and alts:
                    st.markdown("**Alternatives:** " + ", ".join(alts))
            if data.get("entities"):
                tags = [f"`{e['entity']}`" for e in data["entities"]]
                st.markdown("**Entities:** " + ", ".join(tags))
            if data.get("source_url"):
                st.markdown(f"**Source:** [{data.get('source_title', 'Link')}]({data['source_url']})")
            st.caption(f"Relevance score: {score:.2f}")

    else:
        badge = category_badge(data.get("category", ""))
        summary = data.get("summary", "Untitled")
        label = f"{relevance} | {badge} {summary}"

        with st.expander(label):
            if data.get("detail"):
                st.markdown(data["detail"])
            if data.get("components"):
                comps = data["components"]
                if isinstance(comps, list) and comps:
                    st.markdown("**Components:** " + ", ".join(f"`{c}`" for c in comps))
            if data.get("entities"):
                tags = [f"`{e['entity']}`" for e in data["entities"]]
                st.markdown("**Entities:** " + ", ".join(tags))
            st.caption(f"Relevance score: {score:.2f}")


def _build_context_markdown(task_text: str, results: list[dict]) -> str:
    """Build a markdown context file from ranked results."""
    parts: list[str] = []
    parts.append(f"# Context for: {task_text}\n\n")

    decisions = [r for r in results if r["type"] == "decision"]
    learnings = [r for r in results if r["type"] == "learning"]

    if decisions:
        parts.append("## Relevant Decisions\n\n")
        for r in decisions:
            d = r["data"]
            parts.append(f"- **{d.get('summary', '')}** (confidence: {d.get('confidence', '?')})")
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
            if l.get("components"):
                comps = l["components"]
                if isinstance(comps, list) and comps:
                    parts.append(f"\n  Components: {', '.join(comps)}")
            parts.append("\n\n")

    parts.append("---\n*Generated by setkontext*\n")
    return "".join(parts)
