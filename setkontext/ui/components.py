"""Shared UI components for setkontext Streamlit pages."""

from __future__ import annotations

import anthropic
import streamlit as st

from setkontext.config import Config

CATEGORY_LABELS = {
    "bug_fix": "Bug Fix",
    "gotcha": "Gotcha",
    "implementation": "Implementation",
}

CATEGORY_CSS_CLASS = {
    "bug_fix": "bug-fix",
    "gotcha": "gotcha",
    "implementation": "implementation",
}

CONFIDENCE_CSS_CLASS = {
    "high": "high",
    "medium": "medium",
    "low": "low",
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
    """Return an HTML badge for a decision confidence level."""
    css_class = CONFIDENCE_CSS_CLASS.get(confidence, "low")
    label = confidence.upper() if confidence else "UNKNOWN"
    return f'<span class="sk-badge sk-badge-{css_class}">{label}</span>'


def category_badge(category: str) -> str:
    """Return an HTML badge for a learning category."""
    css_class = CATEGORY_CSS_CLASS.get(category, "implementation")
    label = CATEGORY_LABELS.get(category, category.upper())
    return f'<span class="sk-badge sk-badge-{css_class}">{label}</span>'


def type_badge(item_type: str) -> str:
    """Return an HTML badge for item type (decision or learning)."""
    return f'<span class="sk-badge sk-badge-{item_type}">{item_type.upper()}</span>'


def relevance_badge(score: float) -> str:
    """Return an HTML badge for a relevance score."""
    if score >= 0.7:
        css_class, label = "high", "High"
    elif score >= 0.4:
        css_class, label = "medium", "Medium"
    else:
        css_class, label = "low", "Low"
    return f'<span class="sk-badge sk-badge-{css_class}">{label}</span>'


def confidence_label(confidence: str) -> str:
    """Return a plain-text label for confidence (for expander headers)."""
    return (confidence or "unknown").upper()


def category_label(category: str) -> str:
    """Return a plain-text label for category (for expander headers)."""
    return CATEGORY_LABELS.get(category, category.upper())


def render_source_card(item: dict) -> None:
    """Render a compact source card for inline display in chat.

    item: {"type": "decision"|"learning", "score": float, "data": dict}
    """
    data = item["data"]
    item_type = item["type"]
    summary = data.get("summary", "Untitled")

    badge_html = type_badge(item_type)
    if item_type == "decision":
        badge_html += " " + confidence_badge(data.get("confidence", ""))
    else:
        badge_html += " " + category_badge(data.get("category", ""))

    detail = ""
    if item_type == "decision" and data.get("reasoning"):
        detail = data["reasoning"]
    elif item_type == "learning" and data.get("detail"):
        detail = data["detail"]
    if len(detail) > 150:
        detail = detail[:147] + "..."

    detail_html = f'<div class="sk-source-detail">{detail}</div>' if detail else ""
    st.markdown(
        f"""<div class="sk-source-card">
            {badge_html}
            <span class="sk-source-summary">{summary}</span>
            {detail_html}
        </div>""",
        unsafe_allow_html=True,
    )


def render_browse_decision_card(d: dict, relevance_score: float | None = None) -> None:
    """Render a decision card for the Browse mode."""
    summary = d.get("summary", "Untitled")
    conf = confidence_label(d.get("confidence", ""))
    source_type = d.get("source_type", "?").upper()

    label = f"[{conf}] Decision: {summary} -- {source_type}"
    if relevance_score is not None:
        level = "HIGH" if relevance_score >= 0.7 else ("MED" if relevance_score >= 0.4 else "LOW")
        label = f"[{level}] {label}"

    with st.expander(label):
        # Rich badges inside the expanded body
        badges = confidence_badge(d.get("confidence", "")) + " " + type_badge("decision")
        st.markdown(badges, unsafe_allow_html=True)
        if d.get("reasoning"):
            st.markdown(f"**Reasoning:** {d['reasoning']}")
        if d.get("alternatives"):
            alts = d["alternatives"]
            if isinstance(alts, list) and alts:
                st.markdown("**Alternatives:** " + ", ".join(alts))
        if d.get("entities"):
            tags = [f"`{e['entity']}`" for e in d["entities"]]
            st.markdown("**Entities:** " + ", ".join(tags))
        if d.get("source_url"):
            title = d.get("source_title", "Link")
            st.markdown(f"**Source:** [{title}]({d['source_url']})")
        st.caption(
            f"Confidence: {d.get('confidence', 'unknown')} | "
            f"Date: {d.get('decision_date', 'unknown')}"
        )


def render_browse_learning_card(l: dict, relevance_score: float | None = None) -> None:
    """Render a learning card for the Browse mode."""
    summary = l.get("summary", "Untitled")
    cat = category_label(l.get("category", ""))

    label = f"[{cat}] {summary}"
    if relevance_score is not None:
        level = "HIGH" if relevance_score >= 0.7 else ("MED" if relevance_score >= 0.4 else "LOW")
        label = f"[{level}] {label}"

    with st.expander(label):
        badges = category_badge(l.get("category", "")) + " " + type_badge("learning")
        st.markdown(badges, unsafe_allow_html=True)
        if l.get("detail"):
            st.markdown(l["detail"])
        if l.get("components"):
            comps = l["components"]
            if isinstance(comps, list) and comps:
                st.markdown("**Components:** " + ", ".join(f"`{c}`" for c in comps))
        if l.get("entities"):
            tags = [f"`{e['entity']}`" for e in l["entities"]]
            st.markdown("**Entities:** " + ", ".join(tags))
        if l.get("session_date"):
            st.caption(f"Date: {l['session_date']}")


def check_db_exists(config: Config) -> bool:
    """Check if the database file exists, show info message if not."""
    if not config.db_path.exists():
        st.info("No data yet. Run `setkontext extract` or go to Settings to configure.")
        return False
    return True


def get_anthropic_client() -> anthropic.Anthropic | None:
    """Load config and return an Anthropic client, or None."""
    config = Config.load()
    if not config.anthropic_api_key:
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
