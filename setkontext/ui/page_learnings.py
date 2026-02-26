"""Learnings browser and management page."""

from __future__ import annotations

import uuid
from datetime import datetime

import streamlit as st

from setkontext.config import Config
from setkontext.extraction.models import Learning, Source
from setkontext.storage.repository import Repository
from setkontext.ui.components import (
    CATEGORY_LABELS,
    check_db_exists,
    render_learning_card,
)


def render(get_repo) -> None:
    """Render the learnings page."""
    st.header("Session Learnings")
    st.caption("Bugs solved, gotchas discovered, and features implemented across coding sessions.")

    config = Config.load()
    if not check_db_exists(config):
        return

    repo = get_repo()

    # Stats row
    lstats = repo.get_learning_stats()
    cols = st.columns(4)
    cols[0].metric("Total Learnings", lstats["total_learnings"])
    cols[1].metric("Bug Fixes", lstats["bug_fixes"])
    cols[2].metric("Gotchas", lstats["gotchas"])
    cols[3].metric("Implementations", lstats["implementations"])

    if lstats["total_learnings"] == 0:
        st.info(
            "No learnings captured yet. Use `setkontext remember` to save one manually, "
            "or session learnings will be captured automatically at the end of Claude Code sessions."
        )

    # Filters
    st.subheader("Filter")
    filter_cols = st.columns(3)
    with filter_cols[0]:
        cat_options = ["All", "bug_fix", "gotcha", "implementation"]
        cat_labels = ["All"] + [CATEGORY_LABELS.get(c, c) for c in cat_options[1:]]
        cat_idx = st.selectbox(
            "Category",
            range(len(cat_options)),
            format_func=lambda i: cat_labels[i],
            key="learnings_category",
        )
        category_filter = cat_options[cat_idx] if cat_idx > 0 else None
    with filter_cols[1]:
        entities = repo.get_entities()
        entity_names = ["All"] + [e["entity"] for e in entities]
        entity_filter = st.selectbox("Entity", entity_names, key="learnings_entity")
    with filter_cols[2]:
        search_text = st.text_input("Search", placeholder="timeout, auth, caching...", key="learnings_search")

    # Fetch learnings
    learnings = _fetch_learnings(repo, category_filter, entity_filter, search_text)

    if learnings:
        st.write(f"Showing {len(learnings)} learning(s)")
        for l in learnings:
            render_learning_card(l)
    elif lstats["total_learnings"] > 0:
        st.info("No learnings match the current filters.")

    # Add learning form
    st.divider()
    _render_add_form(repo, config)


def _fetch_learnings(
    repo: Repository,
    category: str | None,
    entity_filter: str,
    search_text: str,
) -> list[dict]:
    """Fetch learnings based on current filters."""
    if entity_filter and entity_filter != "All":
        return repo.get_learnings_by_entity(entity_filter)

    if search_text.strip():
        from setkontext.ui.components import build_fts_query

        fts = build_fts_query(search_text)
        if fts:
            results = repo.search_learnings(fts, category=category, limit=50)
            if results:
                return results
        # Fall through to recent if FTS returned nothing
    return repo.get_recent_learnings(limit=50, category=category)


def _render_add_form(repo: Repository, config: Config) -> None:
    """Render the manual 'add learning' form."""
    with st.expander("Add a learning manually"):
        with st.form("add_learning_form"):
            cat = st.selectbox(
                "Category",
                ["bug_fix", "gotcha", "implementation"],
                format_func=lambda c: CATEGORY_LABELS.get(c, c),
                key="add_learning_cat",
            )
            summary = st.text_input("Summary", placeholder="One-sentence description")
            detail = st.text_area("Detail", placeholder="Full context, root cause, fix, etc.")
            components_text = st.text_input(
                "Components", placeholder="Comma-separated file paths (optional)"
            )

            if st.form_submit_button("Save Learning"):
                if not summary.strip():
                    st.error("Summary is required.")
                    return

                components = [
                    c.strip() for c in components_text.split(",") if c.strip()
                ] if components_text else []

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
