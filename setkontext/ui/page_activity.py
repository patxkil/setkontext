"""Agent activity timeline page."""

from __future__ import annotations

import json
from datetime import datetime

import streamlit as st

from setkontext.activity import read_activity_log

TOOL_NAMES = [
    "All",
    "query_decisions",
    "validate_approach",
    "get_decisions_by_entity",
    "list_entities",
    "get_decision_context",
    "recall_learnings",
]

TOOL_COLORS = {
    "query_decisions": "blue",
    "validate_approach": "orange",
    "get_decisions_by_entity": "green",
    "list_entities": "violet",
    "get_decision_context": "gray",
    "recall_learnings": "red",
}


def render(get_repo) -> None:
    """Render the agent activity timeline."""
    st.header("Agent Activity")
    st.caption("See what context your AI agent received from setkontext.")

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        tool_filter = st.selectbox("Tool", TOOL_NAMES, key="activity_tool_filter")
    with col2:
        limit = st.slider("Entries", min_value=10, max_value=100, value=20, key="activity_limit")

    tool_name = tool_filter if tool_filter != "All" else None
    entries = read_activity_log(limit=limit, tool_name=tool_name)

    if not entries:
        st.info(
            "No activity recorded yet. Activity is logged when AI agents call setkontext MCP tools."
        )
        return

    # Summary stats
    _render_summary(entries)

    st.divider()

    # Timeline
    for entry in entries:
        _render_entry(entry)


def _render_summary(entries: list[dict]) -> None:
    """Render summary statistics for the loaded entries."""
    total = len(entries)
    errors = sum(1 for e in entries if e.get("error"))
    durations = [e.get("duration_ms", 0) for e in entries if e.get("duration_ms")]
    avg_duration = sum(durations) // len(durations) if durations else 0

    cols = st.columns(3)
    cols[0].metric("Tool Calls", total)
    cols[1].metric("Errors", errors)
    cols[2].metric("Avg Duration", f"{avg_duration}ms")


def _render_entry(entry: dict) -> None:
    """Render a single activity log entry."""
    ts = entry.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        time_str = ts[:19] if ts else "unknown"

    tool_name = entry.get("tool_name", "unknown")
    duration = entry.get("duration_ms", 0)
    error = entry.get("error")
    args = entry.get("arguments", {})
    preview = entry.get("result_preview", "")

    color = TOOL_COLORS.get(tool_name, "gray")
    status = "error" if error else ""

    # Header
    header = f"**{time_str}** \u2014 :{color}[{tool_name}] \u2014 {duration}ms"
    if error:
        header += " \u274c"

    with st.expander(header):
        if error:
            st.error(f"Error: {error}")

        if args:
            st.markdown("**Arguments:**")
            st.json(args)

        if preview:
            st.markdown("**Result preview:**")
            # Try to format as JSON for readability
            try:
                parsed = json.loads(preview)
                st.json(parsed)
            except (json.JSONDecodeError, TypeError):
                st.code(preview, language="text")
