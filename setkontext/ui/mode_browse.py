"""Browse mode -- unified decisions + learnings with search and tabs."""

from __future__ import annotations

import uuid
from datetime import datetime

import streamlit as st

from setkontext.config import Config
from setkontext.extraction.models import Learning, Source
from setkontext.storage.repository import Repository
from setkontext.ui.components import (
    CATEGORY_LABELS,
    build_fts_query,
    check_db_exists,
    render_browse_decision_card,
    render_browse_learning_card,
)
from setkontext.ui.ranking import build_context_markdown, search_and_rank


def render(get_repo) -> None:
    """Render the browse mode."""
    config = Config.load()
    if not check_db_exists(config):
        return

    repo = get_repo()

    # Combined stats row
    stats = repo.get_stats()
    lstats = repo.get_learning_stats()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _render_stat(stats.get("total_decisions", 0), "Decisions")
    with col2:
        _render_stat(lstats.get("total_learnings", 0), "Learnings")
    with col3:
        _render_stat(stats.get("unique_entities", 0), "Entities")
    with col4:
        _render_stat(stats.get("total_sources", 0), "Sources")

    # Search bar -- the primary interaction
    search_text = st.text_input(
        "Search",
        placeholder="Search decisions and learnings...",
        key="browse_search",
        label_visibility="collapsed",
    )

    # Tabs: All | Decisions | Learnings
    tab_all, tab_decisions, tab_learnings = st.tabs(["All", "Decisions", "Learnings"])

    if search_text.strip():
        # Ranked search mode
        ranked = search_and_rank(repo, search_text, limit=30)
        with tab_all:
            if not ranked:
                st.info("No results found.")
            else:
                st.caption(f"{len(ranked)} result(s)")
                for item in ranked:
                    _render_ranked_item(item)
                _render_download(search_text, ranked)
        with tab_decisions:
            decision_items = [r for r in ranked if r["type"] == "decision"]
            if not decision_items:
                st.info("No matching decisions.")
            else:
                st.caption(f"{len(decision_items)} decision(s)")
                for item in decision_items:
                    _render_ranked_item(item)
        with tab_learnings:
            learning_items = [r for r in ranked if r["type"] == "learning"]
            if not learning_items:
                st.info("No matching learnings.")
            else:
                st.caption(f"{len(learning_items)} learning(s)")
                for item in learning_items:
                    _render_ranked_item(item)
    else:
        # Default browse mode -- recent items
        with tab_all:
            _render_recent_all(repo)
        with tab_decisions:
            _render_decisions_browse(repo)
        with tab_learnings:
            _render_learnings_browse(repo, config)


def _render_stat(value: int, label: str) -> None:
    """Render a stat pill using custom HTML."""
    st.markdown(
        f"""<div class="sk-stat">
            <div class="sk-stat-value">{value}</div>
            <div class="sk-stat-label">{label}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def _render_ranked_item(item: dict) -> None:
    """Render a single ranked result as a card."""
    if item["type"] == "decision":
        render_browse_decision_card(item["data"], relevance_score=item["score"])
    else:
        render_browse_learning_card(item["data"], relevance_score=item["score"])


def _render_recent_all(repo: Repository) -> None:
    """Show interleaved recent decisions and learnings."""
    decisions = repo.get_all_decisions(limit=10)
    learnings = repo.get_recent_learnings(limit=10)

    combined: list[tuple[str, str, dict]] = []
    for d in decisions:
        combined.append(("decision", d.get("extracted_at", ""), d))
    for l in learnings:
        combined.append(("learning", l.get("extracted_at", ""), l))
    combined.sort(key=lambda x: x[1], reverse=True)

    if not combined:
        st.info("No decisions or learnings yet.")
        return

    st.caption(f"{len(combined)} recent item(s)")
    for item_type, _, data in combined[:20]:
        if item_type == "decision":
            render_browse_decision_card(data)
        else:
            render_browse_learning_card(data)


def _render_decisions_browse(repo: Repository) -> None:
    """Decisions tab with type and entity filters."""
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        source_filter = st.selectbox(
            "Source type", ["All", "pr", "adr", "doc", "session"],
            key="browse_decisions_source",
        )
    with filter_col2:
        entities = repo.get_entities()
        entity_names = ["All"] + [e["entity"] for e in entities]
        entity_filter = st.selectbox(
            "Entity", entity_names, key="browse_decisions_entity",
        )

    if entity_filter != "All":
        decisions = repo.get_decisions_by_entity(entity_filter)
    else:
        source_type = source_filter if source_filter != "All" else None
        decisions = repo.get_all_decisions(source_type=source_type, limit=200)

    if not decisions:
        st.info("No decisions match the current filters.")
        return

    st.caption(f"{len(decisions)} decision(s)")
    for d in decisions:
        render_browse_decision_card(d)


def _render_learnings_browse(repo: Repository, config: Config) -> None:
    """Learnings tab with category filter and add form."""
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        cat_options = ["All", "bug_fix", "gotcha", "implementation"]
        cat_labels = ["All"] + [CATEGORY_LABELS.get(c, c) for c in cat_options[1:]]
        cat_idx = st.selectbox(
            "Category",
            range(len(cat_options)),
            format_func=lambda i: cat_labels[i],
            key="browse_learnings_category",
        )
        category_filter = cat_options[cat_idx] if cat_idx > 0 else None
    with filter_col2:
        entities = repo.get_entities()
        entity_names = ["All"] + [e["entity"] for e in entities]
        entity_filter = st.selectbox(
            "Entity", entity_names, key="browse_learnings_entity",
        )

    learnings = _fetch_learnings(repo, category_filter, entity_filter)

    if not learnings:
        st.info("No learnings match the current filters.")
    else:
        st.caption(f"{len(learnings)} learning(s)")
        for l in learnings:
            render_browse_learning_card(l)

    # Add learning form
    st.divider()
    _render_add_learning_form(repo, config)


def _fetch_learnings(
    repo: Repository,
    category: str | None,
    entity_filter: str,
) -> list[dict]:
    """Fetch learnings based on filters."""
    if entity_filter and entity_filter != "All":
        return repo.get_learnings_by_entity(entity_filter)
    return repo.get_recent_learnings(limit=50, category=category)


def _render_add_learning_form(repo: Repository, config: Config) -> None:
    """Render the manual add learning form."""
    with st.expander("Add a learning manually"):
        with st.form("add_learning_form"):
            cat = st.selectbox(
                "Category",
                ["bug_fix", "gotcha", "implementation"],
                format_func=lambda c: CATEGORY_LABELS.get(c, c),
                key="add_learning_cat",
            )
            summary = st.text_input("Summary", placeholder="One-sentence description")
            detail = st.text_area("Detail", placeholder="Full context, root cause, fix...")
            components_text = st.text_input(
                "Components", placeholder="Comma-separated file paths (optional)",
            )
            if st.form_submit_button("Save Learning"):
                if not summary.strip():
                    st.error("Summary is required.")
                    return
                components = (
                    [c.strip() for c in components_text.split(",") if c.strip()]
                    if components_text else []
                )
                repo_name = config.repo or "local"
                source_id = f"learning:manual-{uuid.uuid4().hex[:8]}"
                source = Source(
                    id=source_id,
                    source_type="learning",
                    repo=repo_name,
                    url="",
                    title=f"[manual] {summary[:80]}",
                    raw_content=detail or summary,
                    fetched_at=datetime.now(),
                )
                learning = Learning(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    category=cat,
                    summary=summary,
                    detail=detail,
                    components=components,
                    entities=[],
                    session_date=datetime.now().strftime("%Y-%m-%d"),
                    extracted_at=datetime.now(),
                )
                repo.save_learning_result(source, [learning])
                st.success(f"Saved: {summary}")
                st.rerun()


def _render_download(search_text: str, ranked: list[dict]) -> None:
    """Offer download of context markdown."""
    st.divider()
    context_md = build_context_markdown(search_text, ranked)
    st.download_button(
        "Download as context file",
        data=context_md,
        file_name="context.md",
        mime="text/markdown",
    )
