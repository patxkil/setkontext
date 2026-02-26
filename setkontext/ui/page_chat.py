"""Chat page — conversational Q&A grounded in decisions and learnings."""

from __future__ import annotations

import streamlit as st

from setkontext.config import Config
from setkontext.query.engine import QueryEngine
from setkontext.storage.repository import Repository
from setkontext.ui.components import (
    build_fts_query,
    check_db_exists,
    get_anthropic_client,
    render_decision_card_compact,
    render_learning_card_compact,
)


def render(get_repo) -> None:
    """Render the chat page."""
    st.header("Chat")
    st.caption("Ask questions about your engineering decisions and learnings.")

    config = Config.load()
    if not check_db_exists(config):
        return

    repo = get_repo()

    # Initialize session state
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    # Source filter in sidebar
    source_filter = st.radio(
        "Show sources",
        ["All", "Decisions only", "Learnings only"],
        horizontal=True,
        key="chat_source_filter",
    )

    # Clear button
    if st.button("Clear conversation", key="chat_clear"):
        st.session_state.chat_messages = []
        st.rerun()

    # Render message history
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                _render_sources(msg, source_filter)

    # Chat input
    question = st.chat_input("Ask about engineering decisions...")

    if question:
        # Show user message
        st.session_state.chat_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Searching decisions and learnings..."):
                answer, decisions, learnings = _generate_response(
                    repo, question, st.session_state.chat_messages, source_filter,
                )

            st.markdown(answer)

            msg = {
                "role": "assistant",
                "content": answer,
                "decisions": decisions,
                "learnings": learnings,
            }
            _render_sources(msg, source_filter)

            st.session_state.chat_messages.append(msg)


def _generate_response(
    repo: Repository,
    question: str,
    messages: list[dict],
    source_filter: str,
) -> tuple[str, list[dict], list[dict]]:
    """Generate a chat response with decisions and learnings."""
    decisions: list[dict] = []
    learnings: list[dict] = []

    # Build history (exclude the latest user message we just appended)
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in messages[:-1]
    ]

    # Search decisions
    if source_filter != "Learnings only":
        client = get_anthropic_client()
        if client:
            engine = QueryEngine(repo, client)
            result = engine.chat(question, history)
            answer = result.answer
            decisions = result.decisions
        else:
            answer = "Cannot query decisions without an Anthropic API key."
    else:
        answer = ""

    # Search learnings
    if source_filter != "Decisions only":
        fts = build_fts_query(question)
        if fts:
            learnings = repo.search_learnings(fts, limit=5)
        if not learnings:
            learnings = repo.get_recent_learnings(limit=3)

    # If we only have learnings (no API key or learnings-only mode), build a simple answer
    if not answer and learnings:
        parts = ["Here are relevant learnings from past sessions:\n"]
        for l in learnings:
            parts.append(f"- **{l.get('summary', '')}**")
            if l.get("detail"):
                detail = l["detail"]
                if len(detail) > 150:
                    detail = detail[:147] + "..."
                parts.append(f"  {detail}")
        answer = "\n".join(parts)
    elif not answer:
        answer = "No relevant decisions or learnings found for this question."

    return answer, decisions, learnings


def _render_sources(msg: dict, source_filter: str) -> None:
    """Render source cards for a message."""
    decisions = msg.get("decisions", [])
    learnings = msg.get("learnings", [])

    if not decisions and not learnings:
        return

    show_decisions = source_filter != "Learnings only" and decisions
    show_learnings = source_filter != "Decisions only" and learnings

    if show_decisions or show_learnings:
        st.divider()

    if show_decisions:
        st.caption(f"{len(decisions)} decision(s) found")
        for d in decisions[:5]:
            render_decision_card_compact(d)

    if show_learnings:
        st.caption(f"{len(learnings)} learning(s) found")
        for l in learnings[:5]:
            render_learning_card_compact(l)
