"""Shared UI components for setkontext Streamlit pages."""

from __future__ import annotations

import anthropic
import streamlit as st

from setkontext.config import Config

CATEGORY_COLORS = {
    "bug_fix": "red",
    "gotcha": "orange",
    "implementation": "blue",
}

CATEGORY_LABELS = {
    "bug_fix": "BUG FIX",
    "gotcha": "GOTCHA",
    "implementation": "IMPLEMENTATION",
}

CATEGORY_EMOJI = {
    "bug_fix": "\U0001f41b",
    "gotcha": "\u26a0\ufe0f",
    "implementation": "\U0001f528",
}

CONFIDENCE_EMOJI = {
    "high": "\U0001f7e2",
    "medium": "\U0001f7e1",
    "low": "\U0001f534",
}

STOP_WORDS = {
    "why", "did", "we", "the", "a", "an", "is", "are", "was", "were",
    "do", "does", "how", "what", "when", "where", "which", "who",
    "our", "their", "this", "that", "for", "with", "from", "about",
    "use", "using", "used", "choose", "chose", "chosen", "pick",
    "picked", "decide", "decided", "should", "would", "could",
    "have", "has", "had", "not", "and", "or", "but", "in", "on",
    "to", "of", "it", "its", "be", "been", "being", "need", "want",
    "add", "implement", "create", "build", "make",
}


def confidence_badge(confidence: str) -> str:
    """Return emoji for a decision confidence level."""
    return CONFIDENCE_EMOJI.get(confidence, "\u26aa")


def category_badge(category: str) -> str:
    """Return a colored label string for a learning category."""
    emoji = CATEGORY_EMOJI.get(category, "")
    label = CATEGORY_LABELS.get(category, category.upper())
    return f"{emoji} {label}"


def render_decision_card(d: dict) -> None:
    """Render a single decision as an expandable Streamlit card."""
    badge = confidence_badge(d.get("confidence", ""))
    source_type = d.get("source_type", "?").upper()
    summary = d.get("summary", "Untitled")

    with st.expander(f"{badge} {summary} \u2014 {source_type}"):
        if d.get("reasoning"):
            st.markdown(f"**Reasoning:** {d['reasoning']}")
        if d.get("alternatives"):
            alts = d["alternatives"]
            if isinstance(alts, list) and alts:
                st.markdown("**Alternatives:** " + ", ".join(alts))
        if d.get("entities"):
            tags = [
                f"`{e['entity']}` ({e.get('entity_type', '')})"
                for e in d["entities"]
            ]
            st.markdown("**Entities:** " + ", ".join(tags))
        if d.get("source_url"):
            title = d.get("source_title", "Link")
            st.markdown(f"**Source:** [{title}]({d['source_url']})")
        st.caption(
            f"Confidence: {d.get('confidence', 'unknown')} | "
            f"Date: {d.get('decision_date', 'unknown')}"
        )


def render_learning_card(l: dict) -> None:
    """Render a single learning as an expandable Streamlit card."""
    cat = l.get("category", "unknown")
    badge = category_badge(cat)
    summary = l.get("summary", "Untitled")

    with st.expander(f"{badge} {summary}"):
        if l.get("detail"):
            st.markdown(l["detail"])
        if l.get("components"):
            comps = l["components"]
            if isinstance(comps, list) and comps:
                st.markdown("**Components:** " + ", ".join(f"`{c}`" for c in comps))
        if l.get("entities"):
            tags = [
                f"`{e['entity']}` ({e.get('entity_type', '')})"
                for e in l["entities"]
            ]
            st.markdown("**Entities:** " + ", ".join(tags))
        if l.get("session_date"):
            st.caption(f"Date: {l['session_date']}")


def render_decision_card_compact(d: dict) -> None:
    """Render a compact decision card for inline display in chat."""
    badge = confidence_badge(d.get("confidence", ""))
    summary = d.get("summary", "Untitled")
    st.markdown(
        f"> {badge} **Decision:** {summary}",
    )
    if d.get("reasoning"):
        reasoning = d["reasoning"]
        if len(reasoning) > 200:
            reasoning = reasoning[:197] + "..."
        st.caption(f"Why: {reasoning}")


def render_learning_card_compact(l: dict) -> None:
    """Render a compact learning card for inline display in chat."""
    badge = category_badge(l.get("category", ""))
    summary = l.get("summary", "Untitled")
    st.markdown(f"> {badge} **{summary}**")
    if l.get("detail"):
        detail = l["detail"]
        if len(detail) > 200:
            detail = detail[:197] + "..."
        st.caption(detail)


def check_db_exists(config: Config) -> bool:
    """Check if the database file exists, show info message if not."""
    if not config.db_path.exists():
        st.info("No data yet. Run `setkontext extract` or use the Setup page.")
        return False
    return True


def get_anthropic_client() -> anthropic.Anthropic | None:
    """Load config and return an Anthropic client, or None with error shown."""
    config = Config.load()
    if not config.anthropic_api_key:
        st.error("ANTHROPIC_API_KEY not set. Configure it in the Setup page or environment.")
        return None
    return anthropic.Anthropic(api_key=config.anthropic_api_key)


def build_fts_query(text: str) -> str:
    """Convert free text into an FTS5 query (stop-word removal + OR join)."""
    words = []
    for word in text.lower().split():
        cleaned = "".join(c for c in word if c.isalnum())
        if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 2:
            words.append(cleaned)
    if not words:
        return ""
    return " OR ".join(words)
