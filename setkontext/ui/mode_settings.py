"""Settings mode -- configuration, extraction, and activity log."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from setkontext.activity import read_activity_log
from setkontext.config import Config


# Tool colors for activity log
TOOL_COLORS = {
    "query_decisions": "blue",
    "validate_approach": "orange",
    "get_decisions_by_entity": "green",
    "list_entities": "violet",
    "get_decision_context": "gray",
    "recall_learnings": "red",
}

TOOL_NAMES = [
    "All", "query_decisions", "validate_approach",
    "get_decisions_by_entity", "list_entities",
    "get_decision_context", "recall_learnings",
]


def render(get_repo) -> None:
    """Render the settings mode."""
    config = Config.load()

    tab_config, tab_activity = st.tabs(["Configuration", "Activity Log"])

    with tab_config:
        _render_configuration(config, get_repo)

    with tab_activity:
        _render_activity()


def _render_configuration(config: Config, get_repo) -> None:
    """Configuration section: status, form, extraction, DB stats."""
    st.subheader("Status")

    # Status indicators
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

    _render_hook_status()

    # Configuration form
    st.subheader("Configure")
    st.caption("Set environment variables or create a .env file. CLI: `setkontext init owner/repo`")

    with st.form("config_form"):
        new_repo = st.text_input("Repository (owner/repo)", value=config.repo)
        new_token = st.text_input("GitHub Token", type="password", value="")
        new_api_key = st.text_input("Anthropic API Key", type="password", value="")
        if st.form_submit_button("Save to .env"):
            _save_env(config, new_repo, new_token, new_api_key)

    # Extraction
    st.subheader("Run Extraction")
    if not config.repo or not config.github_token:
        st.warning("Configure repository and GitHub token first.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            pr_limit = st.number_input("Max PRs", min_value=1, max_value=500, value=50)
        with col2:
            skip_prs = st.checkbox("Skip PR extraction")
        if st.button("Run extraction", type="primary"):
            _run_extraction(config, int(pr_limit), skip_prs)

    # Database stats
    if config.db_path.exists():
        st.subheader("Database")
        repo = get_repo()
        stats = repo.get_stats()
        st.json(stats)


def _render_activity() -> None:
    """Activity log section."""
    col1, col2 = st.columns(2)
    with col1:
        tool_filter = st.selectbox("Tool", TOOL_NAMES, key="settings_tool_filter")
    with col2:
        limit = st.slider("Entries", min_value=10, max_value=100, value=20, key="settings_activity_limit")

    tool_name = tool_filter if tool_filter != "All" else None
    entries = read_activity_log(limit=limit, tool_name=tool_name)

    if not entries:
        st.info("No activity recorded yet. Activity is logged when AI agents call setkontext MCP tools.")
        return

    # Summary stats
    total = len(entries)
    errors = sum(1 for e in entries if e.get("error"))
    durations = [e.get("duration_ms", 0) for e in entries if e.get("duration_ms")]
    avg_duration = sum(durations) // len(durations) if durations else 0

    cols = st.columns(3)
    cols[0].metric("Tool Calls", total)
    cols[1].metric("Errors", errors)
    cols[2].metric("Avg Duration", f"{avg_duration}ms")

    st.divider()

    for entry in entries:
        _render_activity_entry(entry)


def _render_hook_status() -> None:
    """Show Claude Code hook configuration status."""
    settings_path = Path(".claude") / "settings.local.json"
    if not settings_path.exists():
        st.info("Claude Code hooks not configured. Run `setkontext init` to set up.")
        return
    try:
        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {})
        session_end = hooks.get("SessionEnd", [])
        has_capture = any(
            "setkontext capture" in h.get("command", "")
            for h in session_end if isinstance(h, dict)
        )
        if has_capture:
            st.success("Session capture hook: configured")
        else:
            st.warning("Session capture hook: not found. Run `setkontext init`.")
    except (json.JSONDecodeError, OSError):
        st.warning("Could not read hook configuration.")


def _save_env(config: Config, new_repo: str, new_token: str, new_api_key: str) -> None:
    """Save configuration to .env file."""
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


def _run_extraction(config: Config, limit: int, skip_prs: bool) -> None:
    """Run the extraction pipeline with progress indicators."""
    import anthropic
    from setkontext.extraction.adr import extract_adr_decisions
    from setkontext.extraction.doc import extract_doc_decisions
    from setkontext.extraction.pr import extract_pr_decisions
    from setkontext.github.client import GitHubClient
    from setkontext.github.fetcher import Fetcher
    from setkontext.storage.db import get_connection
    from setkontext.storage.repository import Repository

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
            source, decisions, relationships = extract_adr_decisions(adr, config.repo)
            repo_store.save_extraction_result(source, decisions)
            repo_store.save_entity_relationships(relationships)
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
                    source, decisions, relationships = extract_doc_decisions(doc, config.repo, anthropic_client)
                    repo_store.save_extraction_result(source, decisions)
                    repo_store.save_entity_relationships(relationships)
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
                source, decisions, relationships = extract_pr_decisions(pr, config.repo, anthropic_client)
                repo_store.save_extraction_result(source, decisions)
                repo_store.save_entity_relationships(relationships)
                for d in decisions:
                    repo_store.save_file_references("decision", d.id, pr.changed_files)
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


def _render_activity_entry(entry: dict) -> None:
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
    header = f"**{time_str}** -- :{color}[{tool_name}] -- {duration}ms"
    if error:
        header += " (error)"

    with st.expander(header):
        if error:
            st.error(f"Error: {error}")
        if args:
            st.markdown("**Arguments:**")
            st.json(args)
        if preview:
            st.markdown("**Result preview:**")
            try:
                parsed = json.loads(preview)
                st.json(parsed)
            except (json.JSONDecodeError, TypeError):
                st.code(preview, language="text")
