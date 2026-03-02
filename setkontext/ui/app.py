"""Streamlit UI for setkontext -- chat-first experience.

Three modes:
1. Chat -- conversational Q&A with inline ranked context
2. Browse -- unified decisions + learnings search
3. Settings -- configuration, extraction, activity log
"""

from __future__ import annotations

import streamlit as st

from setkontext.config import Config
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository
from setkontext.ui.styles import inject_custom_css


@st.cache_resource
def _get_connection():
    config = Config.load()
    return get_connection(config.db_path)


def get_repo() -> Repository:
    return Repository(_get_connection())


def main() -> None:
    st.set_page_config(
        page_title="setkontext",
        page_icon="SK",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    # Inject all custom CSS (warm background, badges, cards, hide sidebar)
    inject_custom_css()

    # Mode selector -- horizontal segmented control at top
    mode = st.segmented_control(
        "mode",
        options=["Chat", "Browse", "Settings"],
        default="Chat",
        key="app_mode",
        label_visibility="collapsed",
    )

    # Route to mode
    if mode == "Browse":
        from setkontext.ui.mode_browse import render
    elif mode == "Settings":
        from setkontext.ui.mode_settings import render
    else:
        from setkontext.ui.mode_chat import render

    render(get_repo)


if __name__ == "__main__":
    main()
