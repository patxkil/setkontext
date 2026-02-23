"""Streamlit UI for setkontext.

Three views:
1. Query — ask questions, get answers with sources
2. Decisions — browse extracted decisions
3. Setup — connect repo, trigger extraction, see progress
"""

from __future__ import annotations

from pathlib import Path

import anthropic
import streamlit as st

from setkontext.config import Config
from setkontext.extraction.adr import extract_adr_decisions
from setkontext.extraction.doc import extract_doc_decisions
from setkontext.extraction.pr import extract_pr_decisions
from setkontext.github.client import GitHubClient
from setkontext.github.fetcher import Fetcher
from setkontext.query.engine import QueryEngine
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository

DB_PATH = Path("setkontext.db")


@st.cache_resource
def _get_connection():
    return get_connection(DB_PATH)


def get_repo() -> Repository:
    conn = _get_connection()
    return Repository(conn)


def main() -> None:
    st.set_page_config(page_title="setkontext", page_icon="🔍", layout="wide")
    st.title("setkontext")
    st.caption("Engineering decisions from your GitHub history")

    page = st.sidebar.radio("Navigate", ["Query", "Decisions", "Setup"])

    if page == "Query":
        render_query_page()
    elif page == "Decisions":
        render_decisions_page()
    elif page == "Setup":
        render_setup_page()


def render_query_page() -> None:
    st.header("Ask about engineering decisions")

    question = st.text_input(
        "Question",
        placeholder="Why did we choose Postgres over MongoDB?",
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        output_format = st.selectbox("Format", ["text", "json"])

    if st.button("Ask", type="primary") and question:
        config = Config.load()
        if not config.anthropic_api_key:
            st.error("ANTHROPIC_API_KEY not set. Configure it in the Setup page or environment.")
            return

        if not DB_PATH.exists():
            st.error("No decisions database found. Run extraction first in the Setup page.")
            return

        repo = get_repo()
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        engine = QueryEngine(repo, client)

        with st.spinner("Searching decisions..."):
            result = engine.query(question)

        if output_format == "json":
            st.json(result.to_json())
        else:
            st.markdown(result.answer)

            if result.decisions:
                st.subheader("Sources")
                for d in result.decisions:
                    with st.expander(f"[{d.get('confidence', '?')}] {d.get('summary', '')}"):
                        if d.get("reasoning"):
                            st.markdown(f"**Reasoning:** {d['reasoning']}")
                        if d.get("alternatives"):
                            alts = d["alternatives"]
                            if isinstance(alts, list):
                                st.markdown(f"**Alternatives:** {', '.join(alts)}")
                        if d.get("source_url"):
                            st.markdown(f"[View source]({d['source_url']})")


def render_decisions_page() -> None:
    st.header("Extracted decisions")

    if not DB_PATH.exists():
        st.info("No decisions yet. Run extraction in the Setup page.")
        return

    repo = get_repo()
    stats = repo.get_stats()

    # Stats row
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Decisions", stats["total_decisions"])
    col2.metric("Unique Entities", stats["unique_entities"])
    col3.metric("PR Sources", stats["pr_sources"])
    col4.metric("ADR Sources", stats["adr_sources"])
    col5.metric("Doc Sources", stats.get("doc_sources", 0))

    # Filters
    st.subheader("Filter")
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        source_filter = st.selectbox("Source type", ["All", "pr", "adr", "doc"])
    with filter_col2:
        entities = repo.get_entities()
        entity_names = ["All"] + [e["entity"] for e in entities]
        entity_filter = st.selectbox("Entity", entity_names)

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
        confidence_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(
            d.get("confidence", ""), "⚪"
        )
        with st.expander(
            f"{confidence_color} {d.get('summary', 'Untitled')} "
            f"— {d.get('source_type', '?').upper()}"
        ):
            if d.get("reasoning"):
                st.markdown(f"**Reasoning:** {d['reasoning']}")
            if d.get("alternatives"):
                alts = d["alternatives"]
                if isinstance(alts, list) and alts:
                    st.markdown("**Alternatives:**")
                    for alt in alts:
                        st.markdown(f"- {alt}")
            if d.get("entities"):
                entity_tags = [
                    f"`{e['entity']}` ({e.get('entity_type', '')})"
                    for e in d["entities"]
                ]
                st.markdown(f"**Entities:** {', '.join(entity_tags)}")
            if d.get("source_url"):
                st.markdown(f"**Source:** [{d.get('source_title', 'Link')}]({d['source_url']})")
            st.caption(f"Confidence: {d.get('confidence', 'unknown')} | Date: {d.get('decision_date', 'unknown')}")


def render_setup_page() -> None:
    st.header("Setup")

    config = Config.load()

    # Current status
    st.subheader("Current configuration")
    if config.repo:
        st.success(f"Repository: {config.repo}")
    else:
        st.warning("No repository configured")

    if config.github_token:
        st.success("GitHub token: configured")
    else:
        st.warning("GitHub token: not set")

    if config.anthropic_api_key:
        st.success("Anthropic API key: configured")
    else:
        st.warning("Anthropic API key: not set")

    # Configuration form
    st.subheader("Configure")
    st.caption("Set environment variables or create a .env file. Use the CLI: `setkontext setup owner/repo`")

    with st.form("config_form"):
        new_repo = st.text_input("Repository (owner/repo)", value=config.repo)
        new_token = st.text_input("GitHub Token", type="password", value="")
        new_api_key = st.text_input("Anthropic API Key", type="password", value="")

        if st.form_submit_button("Save to .env"):
            env_path = Path(".env")
            lines: list[str] = []
            if new_token:
                lines.append(f"SETKONTEXT_GITHUB_TOKEN={new_token}")
            elif config.github_token:
                lines.append(f"SETKONTEXT_GITHUB_TOKEN={config.github_token}")
            if new_repo:
                lines.append(f"SETKONTEXT_REPO={new_repo}")
            if new_api_key:
                lines.append(f"ANTHROPIC_API_KEY={new_api_key}")
            elif config.anthropic_api_key:
                lines.append(f"ANTHROPIC_API_KEY={config.anthropic_api_key}")
            env_path.write_text("\n".join(lines) + "\n")
            st.success("Configuration saved. Reload the page to apply.")

    # Extraction
    st.subheader("Run extraction")
    if not config.repo or not config.github_token:
        st.warning("Configure repository and GitHub token first.")
        return

    col1, col2 = st.columns(2)
    with col1:
        pr_limit = st.number_input("Max PRs to analyze", min_value=1, max_value=500, value=50)
    with col2:
        skip_prs = st.checkbox("Skip PR extraction (ADRs and docs only)")

    if st.button("Run extraction", type="primary"):
        _run_extraction(config, int(pr_limit), skip_prs)

    # Database stats
    if DB_PATH.exists():
        st.subheader("Database")
        repo = get_repo()
        stats = repo.get_stats()
        st.json(stats)


def _run_extraction(config: Config, limit: int, skip_prs: bool) -> None:
    """Run the extraction pipeline with Streamlit progress indicators."""
    conn = get_connection(DB_PATH)
    repo_store = Repository(conn)
    client = GitHubClient(token=config.github_token, repo=config.repo)
    fetcher = Fetcher(client)

    try:
        # ADRs
        with st.spinner("Fetching ADR files..."):
            adrs = fetcher.fetch_adrs()
        st.write(f"Found {len(adrs)} ADR files")

        adr_decisions = 0
        for adr in adrs:
            source, decisions = extract_adr_decisions(adr, config.repo)
            repo_store.save_extraction_result(source, decisions)
            adr_decisions += len(decisions)
        st.write(f"Extracted {adr_decisions} decisions from ADRs")

        # Docs
        with st.spinner("Fetching documentation files..."):
            docs = fetcher.fetch_docs()
        adr_paths = {adr.path for adr in adrs}
        docs = [d for d in docs if d.path not in adr_paths]
        st.write(f"Found {len(docs)} documentation files")

        if docs:
            if not config.anthropic_api_key:
                st.error("Anthropic API key needed for doc extraction")
            else:
                anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
                doc_decisions = 0
                progress = st.progress(0, text="Analyzing docs...")
                for i, doc in enumerate(docs):
                    source, decisions = extract_doc_decisions(doc, config.repo, anthropic_client)
                    repo_store.save_extraction_result(source, decisions)
                    doc_decisions += len(decisions)
                    progress.progress((i + 1) / len(docs), text=f"Analyzed {i + 1}/{len(docs)} docs")
                st.write(f"Extracted {doc_decisions} decisions from docs")

        if not skip_prs:
            with st.spinner(f"Fetching up to {limit} merged PRs..."):
                prs = fetcher.fetch_merged_prs(limit=limit)
            st.write(f"Found {len(prs)} merged PRs")

            if not config.anthropic_api_key:
                st.error("Anthropic API key needed for PR extraction")
                return

            anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

            pr_decisions = 0
            progress = st.progress(0, text="Analyzing PRs...")
            for i, pr in enumerate(prs):
                source, decisions = extract_pr_decisions(pr, config.repo, anthropic_client)
                repo_store.save_extraction_result(source, decisions)
                if decisions:
                    pr_decisions += len(decisions)
                    st.write(f"  PR #{pr.number}: {len(decisions)} decision(s)")
                progress.progress((i + 1) / len(prs), text=f"Analyzed {i + 1}/{len(prs)} PRs")

            st.write(f"Extracted {pr_decisions} decisions from PRs")

        st.success("Extraction complete!")

    except Exception as e:
        st.error(f"Extraction failed: {e}")
    finally:
        client.close()
        conn.close()


if __name__ == "__main__":
    main()
