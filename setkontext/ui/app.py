"""Streamlit UI for setkontext.

Six views:
1. Chat — conversational Q&A grounded in decisions + learnings
2. Context Spotlight — task-scoped relevance ranking
3. Learnings — browse and manage session learnings
4. Decisions — browse extracted decisions
5. Agent Activity — MCP tool call timeline
6. Setup — connect repo, trigger extraction, see progress
"""

from __future__ import annotations

import streamlit as st

from setkontext.config import Config
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository


@st.cache_resource
def _get_connection():
    config = Config.load()
    return get_connection(config.db_path)


def get_repo() -> Repository:
    return Repository(_get_connection())


def main() -> None:
    st.set_page_config(page_title="setkontext", page_icon="\U0001f50d", layout="wide")
    st.title("setkontext")
    st.caption("Engineering decisions & session learnings from your codebase")

    page = st.sidebar.radio(
        "Navigate",
        ["Chat", "Context Spotlight", "Learnings", "Decisions", "Agent Activity", "Setup"],
    )

    if page == "Chat":
        from setkontext.ui.page_chat import render
    elif page == "Context Spotlight":
        from setkontext.ui.page_spotlight import render
    elif page == "Learnings":
        from setkontext.ui.page_learnings import render
    elif page == "Decisions":
        from setkontext.ui.page_decisions import render
    elif page == "Agent Activity":
        from setkontext.ui.page_activity import render
    elif page == "Setup":
        from setkontext.ui.page_setup import render

    render(get_repo)


if __name__ == "__main__":
    main()
