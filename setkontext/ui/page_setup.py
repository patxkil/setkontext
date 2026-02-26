"""Setup and configuration page."""

from __future__ import annotations

import json
from pathlib import Path

import anthropic
import streamlit as st

from setkontext.config import Config
from setkontext.extraction.adr import extract_adr_decisions
from setkontext.extraction.doc import extract_doc_decisions
from setkontext.extraction.pr import extract_pr_decisions
from setkontext.github.client import GitHubClient
from setkontext.github.fetcher import Fetcher
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository


def render(get_repo) -> None:
    """Render the setup page."""
    st.header("Setup")

    config = Config.load()

    # Current status
    st.subheader("Current Configuration")
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

    # Hook status
    _render_hook_status()

    # Configuration form
    st.subheader("Configure")
    st.caption("Set environment variables or create a .env file. Use the CLI: `setkontext init owner/repo`")

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
    st.subheader("Run Extraction")
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
    if config.db_path.exists():
        st.subheader("Database")
        repo = get_repo()
        stats = repo.get_stats()
        st.json(stats)


def _render_hook_status() -> None:
    """Show Claude Code hook configuration status."""
    settings_path = Path(".claude") / "settings.local.json"
    if not settings_path.exists():
        st.info("Claude Code hooks not configured. Run `setkontext init` to set up automatic session capture.")
        return

    try:
        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {})
        session_end = hooks.get("SessionEnd", [])
        has_capture = any(
            "setkontext capture" in h.get("command", "")
            for h in session_end
            if isinstance(h, dict)
        )
        if has_capture:
            st.success("Session capture hook: configured")
        else:
            st.warning("Session capture hook: not found. Run `setkontext init` to configure.")
    except (json.JSONDecodeError, OSError):
        st.warning("Could not read hook configuration.")


def _run_extraction(config: Config, limit: int, skip_prs: bool) -> None:
    """Run the extraction pipeline with Streamlit progress indicators."""
    conn = get_connection(config.db_path)
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
