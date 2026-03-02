"""Custom CSS for the setkontext UI redesign."""

from __future__ import annotations

# Color palette
WARM_BG = "#FAF9F6"
CARD_BG = "#FFFFFF"
BORDER_SUBTLE = "#E8E4DF"
TEXT_PRIMARY = "#1A1A1A"
TEXT_SECONDARY = "#6B6B6B"
ACCENT_WARM = "#C67A4B"


def inject_custom_css() -> None:
    """Inject all custom CSS into the Streamlit page."""
    import streamlit as st

    css = f"""
    <style>
    /* ---- Global ---- */
    .stApp {{
        background-color: {WARM_BG};
    }}

    /* Hide sidebar, hamburger menu, footer */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    #MainMenu,
    footer {{
        display: none !important;
    }}

    /* ---- Chat greeting ---- */
    .sk-greeting {{
        text-align: center;
        padding: 4rem 1rem 2rem;
    }}
    .sk-greeting h1 {{
        font-size: 2rem;
        font-weight: 600;
        color: {TEXT_PRIMARY};
        margin-bottom: 0.5rem;
    }}
    .sk-greeting p {{
        color: {TEXT_SECONDARY};
        font-size: 1rem;
        margin-bottom: 0;
    }}

    /* ---- CSS Badges (replace emojis) ---- */
    .sk-badge {{
        display: inline-block;
        font-size: 0.7rem;
        font-weight: 600;
        padding: 0.15rem 0.5rem;
        border-radius: 9999px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        vertical-align: middle;
        margin-right: 0.25rem;
    }}

    .sk-badge-high {{ background: #DCFCE7; color: #16A34A; }}
    .sk-badge-medium {{ background: #FEF9C3; color: #CA8A04; }}
    .sk-badge-low {{ background: #F3F4F6; color: #6B7280; }}

    .sk-badge-bug-fix {{ background: #FEE2E2; color: #DC2626; }}
    .sk-badge-gotcha {{ background: #FEF3C7; color: #D97706; }}
    .sk-badge-implementation {{ background: #DBEAFE; color: #2563EB; }}

    .sk-badge-decision {{ background: #E0E7FF; color: #4338CA; }}
    .sk-badge-learning {{ background: #FCE7F3; color: #BE185D; }}

    /* ---- Source cards in chat ---- */
    .sk-source-card {{
        background: {CARD_BG};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
        font-size: 0.875rem;
    }}
    .sk-source-card .sk-source-summary {{
        font-weight: 500;
        color: {TEXT_PRIMARY};
    }}
    .sk-source-card .sk-source-detail {{
        color: {TEXT_SECONDARY};
        font-size: 0.8rem;
        margin-top: 0.25rem;
    }}

    /* ---- Browse cards ---- */
    .sk-browse-card {{
        background: {CARD_BG};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.75rem;
    }}

    /* ---- Stats pills ---- */
    .sk-stat {{
        text-align: center;
        background: {CARD_BG};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: 10px;
        padding: 1rem;
    }}
    .sk-stat-value {{
        font-size: 1.5rem;
        font-weight: 700;
        color: {TEXT_PRIMARY};
    }}
    .sk-stat-label {{
        font-size: 0.75rem;
        color: {TEXT_SECONDARY};
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}

    /* ---- Mode switcher refinement ---- */
    [data-testid="stSegmentedControl"] {{
        justify-content: center;
        margin-bottom: 1rem;
    }}

    /* ---- Subtle DB info line ---- */
    .sk-stats-line {{
        text-align: center;
        color: {TEXT_SECONDARY};
        font-size: 0.85rem;
        margin-top: 1.5rem;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
