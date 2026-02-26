"""Decisions browser page."""

from __future__ import annotations

import streamlit as st

from setkontext.config import Config
from setkontext.ui.components import check_db_exists, render_decision_card


def render(get_repo) -> None:
    """Render the decisions browser page."""
    st.header("Extracted Decisions")

    config = Config.load()
    if not check_db_exists(config):
        return

    repo = get_repo()
    stats = repo.get_stats()

    # Stats row
    cols = st.columns(6)
    cols[0].metric("Decisions", stats["total_decisions"])
    cols[1].metric("Entities", stats["unique_entities"])
    cols[2].metric("PRs", stats["pr_sources"])
    cols[3].metric("ADRs", stats["adr_sources"])
    cols[4].metric("Docs", stats.get("doc_sources", 0))
    cols[5].metric("Learnings", stats.get("total_learnings", 0))

    # Filters
    st.subheader("Filter")
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        source_filter = st.selectbox(
            "Source type", ["All", "pr", "adr", "doc", "session"],
            key="decisions_source_filter",
        )
    with filter_col2:
        entities = repo.get_entities()
        entity_names = ["All"] + [e["entity"] for e in entities]
        entity_filter = st.selectbox("Entity", entity_names, key="decisions_entity_filter")

    # Fetch decisions
    if entity_filter != "All":
        decisions = repo.get_decisions_by_entity(entity_filter)
    else:
        source_type = source_filter if source_filter != "All" else None
        decisions = repo.get_all_decisions(source_type=source_type, limit=200)

    if not decisions:
        st.info("No decisions match the current filters.")
        return

    st.write(f"Showing {len(decisions)} decision(s)")

    for d in decisions:
        render_decision_card(d)
