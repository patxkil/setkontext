"""Chat mode -- the hero experience. Greeting state -> conversation with inline context."""

from __future__ import annotations

import streamlit as st

from setkontext.config import Config
from setkontext.query.engine import QueryEngine
from setkontext.storage.repository import Repository
from setkontext.ui.components import (
    build_fts_query,
    check_db_exists,
    get_anthropic_client,
    render_source_card,
)
from setkontext.ui.ranking import search_and_rank


SUGGESTION_CHIPS = [
    "Why did we choose this database?",
    "What patterns should new endpoints follow?",
    "Recent bugs and gotchas to watch for",
]


def render(get_repo) -> None:
    """Render the chat mode."""
    config = Config.load()

    # Initialize session state
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    has_messages = len(st.session_state.chat_messages) > 0

    if not has_messages:
        _render_greeting(config, get_repo)
    else:
        _render_conversation(config, get_repo)


def _render_greeting(config: Config, get_repo) -> None:
    """Show the warm centered greeting with suggestion chips."""
    st.markdown(
        """
        <div class="sk-greeting">
            <h1>What can I help you find?</h1>
            <p>Ask about engineering decisions, learnings, and architectural context</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Suggestion chips as columns of buttons
    cols = st.columns(len(SUGGESTION_CHIPS))
    for i, chip_text in enumerate(SUGGESTION_CHIPS):
        with cols[i]:
            if st.button(chip_text, key=f"chip_{i}", use_container_width=True):
                st.session_state.chat_messages.append(
                    {"role": "user", "content": chip_text}
                )
                st.rerun()

    # Quick stats line if DB exists
    if config.db_path.exists():
        try:
            repo = get_repo()
            stats = repo.get_stats()
            lstats = repo.get_learning_stats()
            total_d = stats.get("total_decisions", 0)
            total_l = lstats.get("total_learnings", 0)
            if total_d or total_l:
                st.markdown(
                    f'<div class="sk-stats-line">{total_d} decisions and {total_l} learnings indexed</div>',
                    unsafe_allow_html=True,
                )
        except Exception:
            pass

    # Chat input (always visible)
    question = st.chat_input("Ask about your engineering context...")
    if question:
        st.session_state.chat_messages.append({"role": "user", "content": question})
        st.rerun()


def _render_conversation(config: Config, get_repo) -> None:
    """Show the conversation with inline context cards."""
    # Clear button -- top right
    col_spacer, col_clear = st.columns([5, 1])
    with col_clear:
        if st.button("Clear", key="chat_clear"):
            st.session_state.chat_messages = []
            st.rerun()

    if not check_db_exists(config):
        return

    repo = get_repo()

    # Render existing messages
    for idx, msg in enumerate(st.session_state.chat_messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                _render_sources_collapsed(msg, idx)

    # Chat input
    question = st.chat_input("Ask about your engineering context...")

    if question:
        st.session_state.chat_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Searching..."):
                answer, ranked_context = _generate_response(
                    repo, question, st.session_state.chat_messages,
                )

            st.markdown(answer)

            msg = {
                "role": "assistant",
                "content": answer,
                "ranked_context": ranked_context,
            }
            _render_sources_collapsed(msg, len(st.session_state.chat_messages))
            st.session_state.chat_messages.append(msg)


def _generate_response(
    repo: Repository,
    question: str,
    messages: list[dict],
) -> tuple[str, list[dict]]:
    """Generate response with AI answer + spotlight-ranked context.

    Returns: (answer_text, ranked_context)
    """
    answer = ""

    # Build history (exclude the latest user message)
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in messages[:-1]
    ]

    # AI-powered answer (decisions)
    client = get_anthropic_client()
    if client:
        engine = QueryEngine(repo, client)
        result = engine.chat(question, history)
        answer = result.answer

    # Spotlight-ranked context (always runs, no API key needed)
    ranked_context = search_and_rank(repo, question, limit=5)

    # Extract learnings for fallback
    learnings = [r["data"] for r in ranked_context if r["type"] == "learning"]

    # Fallback answer if no API key
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

    return answer, ranked_context


def _render_sources_collapsed(msg: dict, msg_idx: int) -> None:
    """Render sources as a collapsible section (progressive disclosure)."""
    ranked = msg.get("ranked_context", [])

    if not ranked:
        return

    with st.expander(f"{len(ranked)} source(s) referenced", expanded=False):
        for item in ranked[:5]:
            render_source_card(item)
