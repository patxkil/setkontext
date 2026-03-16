"""CLI entry point for setkontext."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import typer
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn, TextColumn

from setkontext.activity import read_activity_log
from setkontext.config import Config
from setkontext.context import generate_context_file
from setkontext.extraction.adr import extract_adr_decisions
from setkontext.extraction.consolidation import (
    ConsolidationProposal,
    create_consolidation_source,
    find_consolidation_proposals,
)
from setkontext.entire.fetcher import EntireFetcher
from setkontext.extraction.doc import extract_doc_decisions
from setkontext.extraction.learning import extract_session_learnings
from setkontext.extraction.models import Entity, Learning, Source
from setkontext.extraction.pr import extract_pr_decisions
from setkontext.extraction.session import extract_session_decisions
from setkontext.github.client import GitHubClient
from setkontext.github.fetcher import Fetcher
from setkontext.github.filter import should_skip
from setkontext.query.engine import QueryEngine
from setkontext.query.validator import DecisionValidator
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository

app = typer.Typer(help="Extract engineering decisions from GitHub for AI coding agents.")


def _write_env(project_dir: Path, repo: str, token: str, anthropic_key: str) -> None:
    """Write or update .env file with setkontext credentials."""
    env_path = project_dir / ".env"
    lines: list[str] = []
    lines.append(f"SETKONTEXT_GITHUB_TOKEN={token}")
    lines.append(f"SETKONTEXT_REPO={repo}")
    if anthropic_key:
        lines.append(f"ANTHROPIC_API_KEY={anthropic_key}")

    our_keys = {"SETKONTEXT_GITHUB_TOKEN", "SETKONTEXT_REPO", "ANTHROPIC_API_KEY"}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            key = line.split("=")[0].strip()
            if key and key not in our_keys:
                lines.append(line)

    env_path.write_text("\n".join(lines) + "\n")
    rprint(f"Credentials saved to {env_path}")


def _find_setkontext_source_dir() -> Path:
    """Find the root directory of the setkontext source (where pyproject.toml lives)."""
    # setkontext/ package dir → parent is the project root
    return Path(__file__).resolve().parent.parent


def _write_mcp_config(project_dir: Path) -> None:
    """Create .mcp.json for per-project MCP server configuration."""
    import json
    import shutil

    mcp_config_path = project_dir / ".mcp.json"

    setkontext_bin = shutil.which("setkontext")
    if setkontext_bin:
        command, args = setkontext_bin, ["serve"]
    else:
        # Fall back to uv run, pointing at the setkontext source directory
        source_dir = _find_setkontext_source_dir()
        command, args = "uv", [
            "run", "--directory", str(source_dir),
            "setkontext", "serve",
        ]

    config = {
        "mcpServers": {
            "setkontext": {
                "type": "stdio",
                "command": command,
                "args": args,
                "env": {
                    "SETKONTEXT_DB_PATH": str(project_dir / "setkontext.db"),
                    "SETKONTEXT_LOG_PATH": str(project_dir / "setkontext-activity.jsonl"),
                },
            }
        }
    }

    mcp_config_path.write_text(json.dumps(config, indent=2) + "\n")
    rprint(f"MCP config written to {mcp_config_path}")


def _update_gitignore(project_dir: Path) -> None:
    """Ensure .gitignore includes setkontext files that shouldn't be committed."""
    gitignore_path = project_dir / ".gitignore"
    entries_to_add = ["setkontext.db", "setkontext-activity.jsonl", ".env"]

    existing_lines: set[str] = set()
    if gitignore_path.exists():
        existing_lines = set(gitignore_path.read_text().splitlines())

    new_entries = [e for e in entries_to_add if e not in existing_lines]
    if new_entries:
        with open(gitignore_path, "a") as f:
            if existing_lines and not gitignore_path.read_text().endswith("\n"):
                f.write("\n")
            f.write("\n# setkontext\n")
            for entry in new_entries:
                f.write(f"{entry}\n")
        rprint(f"Added {', '.join(new_entries)} to .gitignore")


def _write_hooks_config(project_dir: Path) -> None:
    """Create or update .claude/settings.local.json with SessionEnd hook."""
    import json
    import shutil

    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings_path = claude_dir / "settings.local.json"

    # Load existing settings if present
    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            existing = {}

    # Determine the capture command
    setkontext_bin = shutil.which("setkontext")
    db_path = str(project_dir / "setkontext.db")
    if setkontext_bin:
        capture_cmd = f"{setkontext_bin} capture --db-path {db_path}"
    else:
        source_dir = _find_setkontext_source_dir()
        capture_cmd = f"uv run --directory {source_dir} setkontext capture --db-path {db_path}"

    hook_entry = {
        "type": "command",
        "command": capture_cmd,
    }

    # Merge into existing hooks without overwriting other tools' hooks
    hooks = existing.get("hooks", {})
    session_end_hooks = hooks.get("SessionEnd", [])

    # Check if we already have a setkontext capture hook
    already_configured = any(
        "setkontext capture" in h.get("command", "")
        for h in session_end_hooks
        if isinstance(h, dict)
    )

    if not already_configured:
        session_end_hooks.append(hook_entry)
        hooks["SessionEnd"] = session_end_hooks
        existing["hooks"] = hooks
        settings_path.write_text(json.dumps(existing, indent=2) + "\n")
        rprint(f"Claude Code hook configured in {settings_path}")
    else:
        rprint(f"Claude Code hook already configured in {settings_path}")


@app.command()
def init(
    repo: str = typer.Argument(help="GitHub repository (owner/repo)"),
    token: str = typer.Option(
        ..., prompt=True, hide_input=True, help="GitHub personal access token"
    ),
    anthropic_key: str = typer.Option(
        None, "--anthropic-key",
        prompt="Anthropic API key (for decision extraction and queries)",
        hide_input=True,
        help="Anthropic API key",
    ),
) -> None:
    """Initialize setkontext in a project directory.

    Sets up credentials, creates .mcp.json for Claude Code/Cursor,
    and adds setkontext files to .gitignore. Run in your project root.
    """
    project_dir = Path.cwd()

    _write_env(project_dir, repo, token, anthropic_key or "")
    _write_mcp_config(project_dir)
    _write_hooks_config(project_dir)
    _update_gitignore(project_dir)

    rprint(f"\n[green bold]setkontext initialized for {repo}[/green bold]")
    rprint("\nNext steps:")
    rprint("  1. Run [bold]setkontext extract[/bold] to pull decisions from GitHub")
    rprint("  2. Restart Claude Code — it picks up the MCP server automatically")
    rprint("  3. Your agent now has setkontext tools for querying decisions")
    rprint("  4. Session learnings are captured automatically at end of each session")


@app.command()
def serve() -> None:
    """Start the MCP server (called by Claude Code / Cursor automatically)."""
    import asyncio
    from setkontext.mcp_server import main as mcp_main
    asyncio.run(mcp_main())


@app.command()
def extract(
    limit: int = typer.Option(50, help="Max number of PRs to analyze"),
    skip_prs: bool = typer.Option(False, help="Skip PR extraction (ADRs and docs only)"),
    full: bool = typer.Option(False, "--full", help="Force full re-extraction (ignore watermarks)"),
    include_sessions: bool = typer.Option(
        False, "--include-sessions",
        help="Include Entire.io agent session transcripts (requires entire/checkpoints/v1 branch)",
    ),
    session_limit: int = typer.Option(50, help="Max number of sessions to analyze"),
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Extract decisions from the configured repository."""
    config = Config.load()
    issues = config.validate()
    if issues:
        for issue in issues:
            rprint(f"[red]Config error: {issue}[/red]")
        raise typer.Exit(1)

    db = Path(db_path)
    if db.exists():
        rprint("[yellow]Database already exists. New decisions will be merged (existing ones updated).[/yellow]")

    conn = get_connection(db)
    repo_store = Repository(conn)

    client = GitHubClient(token=config.github_token, repo=config.repo)
    fetcher = Fetcher(client)

    anthropic_client: anthropic.Anthropic | None = None

    def _get_anthropic_client() -> anthropic.Anthropic:
        nonlocal anthropic_client
        if anthropic_client is None:
            anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        return anthropic_client

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        ) as progress:
            # Fetch and extract ADRs
            progress.add_task("Fetching ADR files...", total=None)
            adrs = fetcher.fetch_adrs()

            # Incremental: skip ADRs with unchanged content
            seen_adr_hashes = json.loads(repo_store.get_watermark("adr", "content_hashes") or "{}")
            if not full and seen_adr_hashes:

                new_adrs = []
                for adr in adrs:
                    content_hash = hashlib.sha256(adr.content.encode()).hexdigest()[:16]
                    if seen_adr_hashes.get(adr.path) != content_hash:
                        new_adrs.append(adr)
                skipped_adrs = len(adrs) - len(new_adrs)
                if skipped_adrs:
                    rprint(f"Found [bold]{len(adrs)}[/bold] ADR files ({skipped_adrs} unchanged, skipping)")
                else:
                    rprint(f"Found [bold]{len(adrs)}[/bold] ADR files")
                adrs = new_adrs
            else:
                rprint(f"Found [bold]{len(adrs)}[/bold] ADR files")

            adr_decision_count = 0
            for adr in adrs:
                source, decisions, relationships = extract_adr_decisions(adr, config.repo)
                repo_store.save_extraction_result(source, decisions)
                repo_store.save_entity_relationships(relationships)
                adr_decision_count += len(decisions)

            # Update ADR content hashes watermark
            for adr in adrs:
                seen_adr_hashes[adr.path] = hashlib.sha256(adr.content.encode()).hexdigest()[:16]
            repo_store.set_watermark("adr", "content_hashes", json.dumps(seen_adr_hashes))

            rprint(f"Extracted [bold]{adr_decision_count}[/bold] decisions from ADRs")

            # Fetch and extract general documentation
            progress.add_task("Fetching documentation files...", total=None)
            docs = fetcher.fetch_docs()
            # Exclude files already processed as ADRs
            all_adr_paths = set(seen_adr_hashes.keys())
            docs = [d for d in docs if d.path not in all_adr_paths]

            # Incremental: skip docs with unchanged content
            seen_doc_hashes = json.loads(repo_store.get_watermark("doc", "content_hashes") or "{}")
            if not full and seen_doc_hashes:
                new_docs = []
                for doc in docs:
                    content_hash = hashlib.sha256(doc.content.encode()).hexdigest()[:16]
                    if seen_doc_hashes.get(doc.path) != content_hash:
                        new_docs.append(doc)
                skipped_docs = len(docs) - len(new_docs)
                if skipped_docs:
                    rprint(f"Found [bold]{len(docs)}[/bold] documentation files ({skipped_docs} unchanged, skipping)")
                else:
                    rprint(f"Found [bold]{len(docs)}[/bold] documentation files")
                docs = new_docs
            else:
                rprint(f"Found [bold]{len(docs)}[/bold] documentation files")

            if docs:
                doc_client = _get_anthropic_client()
                doc_decision_count = 0

                task = progress.add_task("Analyzing docs for decisions...", total=len(docs))
                for doc in docs:
                    rprint(f"  Analyzing {doc.path}...")
                    source, decisions, relationships = extract_doc_decisions(doc, config.repo, doc_client)
                    repo_store.save_extraction_result(source, decisions)
                    repo_store.save_entity_relationships(relationships)
                    doc_decision_count += len(decisions)
                    rprint(f"    → [green]{len(decisions)} decision(s)[/green]")
                    progress.update(task, advance=1)

                # Update doc content hashes watermark
                for doc in docs:
                    seen_doc_hashes[doc.path] = hashlib.sha256(doc.content.encode()).hexdigest()[:16]
                repo_store.set_watermark("doc", "content_hashes", json.dumps(seen_doc_hashes))

                rprint(f"Extracted [bold]{doc_decision_count}[/bold] decisions from docs")

            if not skip_prs:
                # Incremental: only fetch PRs merged after last extraction
                pr_since: datetime | None = None
                if not full:
                    last_merged = repo_store.get_watermark("pr", "last_merged_at")
                    if last_merged:
                        pr_since = datetime.fromisoformat(last_merged)
                        rprint(f"[dim]Incremental: fetching PRs merged after {pr_since.date()}[/dim]")

                progress.add_task(f"Fetching up to {limit} merged PRs...", total=None)
                prs = fetcher.fetch_merged_prs(since=pr_since, limit=limit)
                rprint(f"Found [bold]{len(prs)}[/bold] merged PRs")

                if prs:
                    pr_client = _get_anthropic_client()
                    pr_decision_count = 0
                    pr_with_decisions = 0
                    pr_skipped = 0

                    task = progress.add_task("Analyzing PRs for decisions...", total=len(prs))
                    for pr in prs:
                        # Smart filtering: skip PRs unlikely to contain decisions
                        filter_result = should_skip(pr)
                        if filter_result.skip:
                            pr_skipped += 1
                            rprint(f"  [dim]PR #{pr.number}: skipped ({filter_result.reason})[/dim]")
                            progress.update(task, advance=1)
                            continue

                        source, decisions, relationships = extract_pr_decisions(pr, config.repo, pr_client)
                        repo_store.save_extraction_result(source, decisions)
                        repo_store.save_entity_relationships(relationships)
                        for d in decisions:
                            repo_store.save_file_references("decision", d.id, pr.changed_files)
                        if decisions:
                            pr_with_decisions += 1
                            pr_decision_count += len(decisions)
                            rprint(f"  PR #{pr.number}: [green]{len(decisions)} decision(s)[/green]")
                        progress.update(task, advance=1)

                    analyzed = len(prs) - pr_skipped
                    rprint(
                        f"Extracted [bold]{pr_decision_count}[/bold] decisions from "
                        f"[bold]{pr_with_decisions}[/bold] PRs "
                        f"(analyzed {analyzed}, skipped {pr_skipped})"
                    )

                # Update PR watermark to latest merged_at timestamp
                if prs:
                    latest_merged = max(
                        (pr.merged_at for pr in prs if pr.merged_at),
                        default=None,
                    )
                    if latest_merged:
                        repo_store.set_watermark("pr", "last_merged_at", latest_merged)

            # Fetch and extract Entire.io sessions
            if include_sessions:
                progress.add_task("Scanning for Entire.io sessions...", total=None)
                entire_fetcher = EntireFetcher(repo_dir=Path.cwd())

                if entire_fetcher.has_checkpoint_branch():
                    sessions = entire_fetcher.fetch_sessions(limit=session_limit)
                    rprint(f"Found [bold]{len(sessions)}[/bold] Entire.io sessions")

                    if sessions:
                        session_client = _get_anthropic_client()
                        session_decision_count = 0
                        sessions_with_decisions = 0

                        task = progress.add_task("Analyzing sessions for decisions...", total=len(sessions))
                        for session in sessions:
                            source, decisions, relationships = extract_session_decisions(
                                session, config.repo, session_client
                            )
                            repo_store.save_extraction_result(source, decisions)
                            repo_store.save_entity_relationships(relationships)
                            if decisions:
                                sessions_with_decisions += 1
                                session_decision_count += len(decisions)
                                rprint(
                                    f"  Session {session.checkpoint_id[:8]}: "
                                    f"[green]{len(decisions)} decision(s)[/green]"
                                )
                            progress.update(task, advance=1)

                        rprint(
                            f"Extracted [bold]{session_decision_count}[/bold] decisions from "
                            f"[bold]{sessions_with_decisions}[/bold] sessions "
                            f"({len(sessions) - sessions_with_decisions} sessions had no decisions)"
                        )
                else:
                    rprint("[yellow]No Entire.io checkpoint branch found. Skipping session extraction.[/yellow]")
                    rprint("  Install Entire.io (https://entire.io) and run agent sessions to populate this.")

        # Print summary
        stats = repo_store.get_stats()
        rprint("\n[bold]Extraction complete:[/bold]")
        rprint(f"  Total decisions: {stats['total_decisions']}")
        rprint(f"  Unique entities: {stats['unique_entities']}")
        source_parts = [
            f"{stats['pr_sources']} PRs",
            f"{stats['adr_sources']} ADRs",
            f"{stats.get('doc_sources', 0)} docs",
        ]
        if stats.get("session_sources", 0) > 0:
            source_parts.append(f"{stats['session_sources']} sessions")
        rprint(f"  Sources: {', '.join(source_parts)}")

        if stats["total_decisions"] == 0:
            rprint("\n[yellow]No decisions were extracted.[/yellow]")
            rprint("This can happen if the repository has no PRs, ADRs, or architecture docs.")
            rprint("Try increasing --limit or check that the repository has documented decisions.")
        else:
            rprint("\n[bold]Try it out:[/bold]")
            rprint('  setkontext query "Why did we choose this tech stack?"')
            rprint("  setkontext stats")

    finally:
        client.close()
        conn.close()


@app.command()
def query(
    question: str = typer.Argument(help="Question about engineering decisions"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Query extracted decisions."""
    config = Config.load()
    if not config.anthropic_api_key:
        rprint("[red]ANTHROPIC_API_KEY not set[/red]")
        raise typer.Exit(1)

    db = Path(db_path)
    if not db.exists():
        rprint(f"[red]Database not found at {db}. Run 'setkontext extract' first.[/red]")
        raise typer.Exit(1)

    conn = get_connection(db)
    repo_store = Repository(conn)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    engine = QueryEngine(repo_store, anthropic_client)

    try:
        result = engine.query(question)

        if format == "json":
            typer.echo(result.to_json())
        else:
            rprint(result.to_text())
    finally:
        conn.close()


@app.command()
def stats(
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Show statistics about extracted decisions."""
    db = Path(db_path)
    if not db.exists():
        rprint(f"[red]Database not found at {db}. Run 'setkontext extract' first.[/red]")
        raise typer.Exit(1)

    conn = get_connection(db)
    repo_store = Repository(conn)

    try:
        s = repo_store.get_stats()
        rprint("[bold]setkontext statistics:[/bold]")
        rprint(f"  Total decisions: {s['total_decisions']}")
        rprint(f"  Unique entities: {s['unique_entities']}")
        rprint(f"  PR sources:      {s['pr_sources']}")
        rprint(f"  ADR sources:     {s['adr_sources']}")
        rprint(f"  Doc sources:     {s.get('doc_sources', 0)}")
        if s.get("session_sources", 0) > 0:
            rprint(f"  Session sources: {s['session_sources']}")

        if s.get("total_learnings", 0) > 0:
            rprint(f"\n[bold]Learnings:[/bold]")
            rprint(f"  Total:           {s['total_learnings']}")
            rprint(f"  Bug fixes:       {s.get('bug_fixes', 0)}")
            rprint(f"  Gotchas:         {s.get('gotchas', 0)}")
            rprint(f"  Implementations: {s.get('implementations', 0)}")

        entities = repo_store.get_entities()
        if entities:
            rprint("\n[bold]Top entities:[/bold]")
            for e in entities[:15]:
                rprint(f"  {e['entity']} ({e['entity_type']}): {e['decision_count']} decision(s)")
    finally:
        conn.close()


@app.command()
def generate(
    output: str = typer.Option("CLAUDE.md", "--output", "-o", help="Output file path"),
    format: str = typer.Option(
        "claude", "--format", "-f", help="Format: claude (CLAUDE.md), cursor (.cursorrules), generic"
    ),
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Generate a context file for AI coding agents.

    Creates a CLAUDE.md, .cursorrules, or generic markdown file containing
    your team's engineering decisions. AI agents load these automatically
    as system context.
    """
    db = Path(db_path)
    if not db.exists():
        rprint(f"[red]Database not found at {db}. Run 'setkontext extract' first.[/red]")
        raise typer.Exit(1)

    conn = get_connection(db)
    repo_store = Repository(conn)

    try:
        # Default output paths per format
        if output == "CLAUDE.md" and format == "cursor":
            output = ".cursorrules"

        out_path = generate_context_file(repo_store, Path(output), format)
        rprint(f"[green]Generated {out_path}[/green]")

        stats = repo_store.get_stats()
        rprint(f"  {stats['total_decisions']} decisions, {stats['unique_entities']} entities")
    finally:
        conn.close()


@app.command()
def activity(
    limit: int = typer.Option(20, help="Number of recent entries to show"),
    tool: str = typer.Option(None, "--tool", "-t", help="Filter by tool name"),
    output_json: bool = typer.Option(False, "--json", help="Output raw JSONL"),
    log_path: str = typer.Option(None, "--log-path", help="Path to activity log file"),
) -> None:
    """Show recent MCP tool activity.

    Displays what context setkontext gave to AI agents, including queries,
    validation results, and which decisions were surfaced.
    """
    path = Path(log_path) if log_path else None
    entries = read_activity_log(limit=limit, tool_name=tool, log_path=path)

    if not entries:
        rprint("[yellow]No activity recorded yet.[/yellow]")
        rprint("Activity is logged when AI agents call setkontext MCP tools.")
        rprint("Make sure your agent has used setkontext tools at least once.")
        raise typer.Exit(0)

    if output_json:
        for entry in entries:
            typer.echo(json.dumps(entry, default=str))
        return

    rprint(f"[bold]Recent setkontext activity[/bold] ({len(entries)} entries)\n")

    for entry in entries:
        ts = entry.get("timestamp", "")
        # Show just time portion if it's today
        try:
            dt = datetime.fromisoformat(ts)
            time_str = dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            time_str = ts[:19] if ts else "??:??:??"

        tool_name = entry.get("tool_name", "unknown")
        duration = entry.get("duration_ms", 0)
        error = entry.get("error")
        args = entry.get("arguments", {})
        preview = entry.get("result_preview", "")

        # Tool name with color
        if error:
            rprint(f"[dim]{time_str}[/dim] [red]{tool_name}[/red]")
            rprint(f"  [red]Error: {error}[/red]")
        else:
            rprint(f"[dim]{time_str}[/dim] [cyan bold]{tool_name}[/cyan bold]")
            _print_tool_summary(tool_name, args, preview, duration)

        rprint("")  # blank line between entries


def _print_tool_summary(tool_name: str, args: dict, preview: str, duration: int) -> None:
    """Print a human-readable summary line for a tool call."""
    import json as json

    if tool_name == "query_decisions":
        question = args.get("question", "")
        # Count decisions in result
        decision_count = _count_decisions_in_preview(preview)
        rprint(f'  Question: "{question}"')
        rprint(f"  [dim]→ {duration}ms, {decision_count} decision(s) matched[/dim]")

    elif tool_name == "validate_approach":
        approach = args.get("proposed_approach", "")
        if len(approach) > 80:
            approach = approach[:77] + "..."
        verdict = _extract_json_field(preview, "verdict")
        conflicts = _count_json_array(preview, "conflicts")
        verdict_color = {
            "CONFLICTS": "red",
            "ALIGNS": "green",
            "NO_COVERAGE": "yellow",
        }.get(verdict, "white")
        rprint(f'  Approach: "{approach}"')
        detail = f"{conflicts} conflict(s)" if verdict == "CONFLICTS" else ""
        rprint(f"  [dim]→[/dim] [{verdict_color}]{verdict}[/{verdict_color}]"
               + (f" ({detail})" if detail else "")
               + f"[dim], {duration}ms[/dim]")

    elif tool_name == "get_decisions_by_entity":
        entity = args.get("entity", "")
        decision_count = _extract_json_field(preview, "decision_count")
        rprint(f'  Entity: "{entity}"')
        rprint(f"  [dim]→ {decision_count or '?'} decision(s), {duration}ms[/dim]")

    elif tool_name == "list_entities":
        entity_count = _extract_json_field(preview, "total_entities")
        rprint(f"  [dim]→ {entity_count or '?'} entities, {duration}ms[/dim]")

    elif tool_name == "get_decision_context":
        rprint(f"  [dim]→ Full context loaded, {duration}ms[/dim]")

    else:
        rprint(f"  [dim]→ {duration}ms[/dim]")


def _count_decisions_in_preview(preview: str) -> int:
    """Try to count decisions from a result preview."""
    import json as json
    try:
        data = json.loads(preview)
        if isinstance(data.get("decisions"), list):
            return len(data["decisions"])
        return data.get("sources_searched", 0)
    except (json.JSONDecodeError, TypeError):
        return 0


def _extract_json_field(preview: str, field: str) -> str:
    """Try to extract a field from a JSON preview."""
    import json as json
    try:
        data = json.loads(preview)
        return str(data.get(field, ""))
    except (json.JSONDecodeError, TypeError):
        return ""


def _count_json_array(preview: str, field: str) -> int:
    """Try to count items in a JSON array field."""
    import json as json
    try:
        data = json.loads(preview)
        arr = data.get(field, [])
        return len(arr) if isinstance(arr, list) else 0
    except (json.JSONDecodeError, TypeError):
        return 0


@app.command()
def capture(
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
    repo: str = typer.Option(None, help="Repository name (reads from .env if not set)"),
) -> None:
    """Capture learnings from a session transcript (reads from stdin).

    Called automatically by the Claude Code SessionEnd hook.
    Reads a session transcript from stdin and extracts bugs, gotchas,
    and implementations using Claude.
    """
    config = Config.load()
    repo_name = repo or config.repo

    if not config.anthropic_api_key:
        print("No ANTHROPIC_API_KEY set, skipping learning capture.", file=sys.stderr)
        raise typer.Exit(0)

    if not repo_name:
        print("No repo configured. Run 'setkontext init' first.", file=sys.stderr)
        raise typer.Exit(1)

    # Read transcript from stdin
    if sys.stdin.isatty():
        print("No transcript on stdin. Pipe a session transcript to this command.", file=sys.stderr)
        raise typer.Exit(0)

    transcript = sys.stdin.read()
    if not transcript.strip():
        raise typer.Exit(0)

    # Try to parse as JSON to extract metadata
    session_metadata: dict = {}
    try:
        data = json.loads(transcript)
        if isinstance(data, dict):
            session_metadata = {
                "session_id": data.get("session_id", ""),
                "agent": data.get("agent", "claude-code"),
                "branch": data.get("branch", ""),
                "prompt": data.get("prompt", ""),
                "summary": data.get("summary", ""),
                "files_touched": data.get("files_touched", []),
            }
            # Use transcript field if present, otherwise use the full text
            transcript = data.get("transcript", transcript)
            if isinstance(transcript, list):
                # JSONL-style transcript — flatten to text
                parts = []
                for entry in transcript:
                    if isinstance(entry, dict):
                        role = entry.get("role", entry.get("type", ""))
                        content = entry.get("content", entry.get("message", ""))
                        if isinstance(content, str) and content:
                            parts.append(f"**{role}:** {content[:500]}")
                    elif isinstance(entry, str):
                        parts.append(entry)
                transcript = "\n\n".join(parts)
    except (json.JSONDecodeError, TypeError):
        pass  # Not JSON, use raw text

    db = Path(db_path)
    conn = get_connection(db)
    repo_store = Repository(conn)

    try:
        anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        source, learnings = extract_session_learnings(
            transcript=transcript if isinstance(transcript, str) else str(transcript),
            repo=repo_name,
            client=anthropic_client,
            session_metadata=session_metadata,
        )
        repo_store.save_learning_result(source, learnings)

        if learnings:
            categories: dict[str, int] = {}
            for l in learnings:
                categories[l.category] = categories.get(l.category, 0) + 1
            parts = [f"{count} {cat.replace('_', ' ')}(s)" for cat, count in categories.items()]
            print(f"Captured {len(learnings)} learnings: {', '.join(parts)}", file=sys.stderr)
        else:
            print("No learnings extracted from this session.", file=sys.stderr)
    finally:
        conn.close()


@app.command()
def remember(
    category: str = typer.Option(
        ..., "--category", "-c",
        help="Learning type: bug_fix, gotcha, or implementation",
    ),
    summary: str = typer.Option(
        ..., "--summary", "-s",
        help="One-sentence summary of the learning",
    ),
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Manually save a learning. Reads detail from stdin if piped.

    Examples:
        setkontext remember -c bug_fix -s "Race condition in session cleanup"
        echo "The root cause was..." | setkontext remember -c gotcha -s "Token refresh timing"
    """
    valid_categories = {"bug_fix", "gotcha", "implementation"}
    if category not in valid_categories:
        rprint(f"[red]Invalid category: {category}. Must be one of: {', '.join(valid_categories)}[/red]")
        raise typer.Exit(1)

    # Read detail from stdin if piped
    detail = ""
    if not sys.stdin.isatty():
        detail = sys.stdin.read().strip()

    config = Config.load()
    repo_name = config.repo or "local"

    db = Path(db_path)
    conn = get_connection(db)
    repo_store = Repository(conn)

    try:
        source_id = f"learning:manual-{uuid.uuid4().hex[:8]}"

        source = Source(
            id=source_id,
            source_type="learning",
            repo=repo_name,
            url="",
            title=f"[manual] {summary[:80]}",
            raw_content=detail or summary,
            fetched_at=datetime.now(),
        )

        learning = Learning(
            id=str(uuid.uuid4()),
            source_id=source_id,
            category=category,
            summary=summary,
            detail=detail,
            components=[],
            entities=[],
            session_date=datetime.now().strftime("%Y-%m-%d"),
            extracted_at=datetime.now(),
        )

        repo_store.save_learning_result(source, [learning])

        category_label = category.replace("_", " ")
        rprint(f"[green]Saved {category_label}:[/green] {summary}")
    finally:
        conn.close()


@app.command()
def recall(
    query: str = typer.Argument(help="What to search for"),
    category: str = typer.Option(
        None, "--category", "-c",
        help="Filter: bug_fix, gotcha, implementation",
    ),
    limit: int = typer.Option(10, help="Max results"),
    format: str = typer.Option("text", "--format", "-f", help="Output format: text or json"),
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Search past learnings — bugs, gotchas, and implementations."""
    import json as json

    db = Path(db_path)
    if not db.exists():
        rprint(f"[red]Database not found at {db}. Run 'setkontext extract' or 'setkontext remember' first.[/red]")
        raise typer.Exit(1)

    conn = get_connection(db)
    repo_store = Repository(conn)

    try:
        # Build FTS query
        stop_words = {
            "why", "did", "we", "the", "a", "an", "is", "are", "was", "were",
            "do", "does", "how", "what", "when", "where", "which", "who",
            "should", "would", "could", "have", "has", "had", "not", "and",
            "or", "but", "in", "on", "to", "of", "it", "be",
        }
        words = []
        for word in query.lower().split():
            cleaned = "".join(c for c in word if c.isalnum())
            if cleaned and cleaned not in stop_words and len(cleaned) > 2:
                words.append(cleaned)

        fts_query = " OR ".join(words) if words else query
        learnings = repo_store.search_learnings(fts_query, category=category, limit=limit)

        # Fall back to recent if no FTS results
        if not learnings:
            learnings = repo_store.get_recent_learnings(limit=limit, category=category)

        if not learnings:
            rprint("[yellow]No learnings found.[/yellow]")
            rprint("Use 'setkontext remember' to save learnings, or sessions will be captured automatically.")
            raise typer.Exit(0)

        if format == "json":
            typer.echo(json.dumps(learnings, indent=2, default=str))
            return

        rprint(f"[bold]Found {len(learnings)} learning(s)[/bold]\n")

        category_colors = {
            "bug_fix": "red",
            "gotcha": "yellow",
            "implementation": "green",
        }
        category_labels = {
            "bug_fix": "BUG FIX",
            "gotcha": "GOTCHA",
            "implementation": "IMPLEMENTATION",
        }

        for l in learnings:
            cat = l.get("category", "unknown")
            color = category_colors.get(cat, "white")
            label = category_labels.get(cat, cat.upper())

            rprint(f"[{color} bold][{label}][/{color} bold] {l.get('summary', '')}")
            if l.get("detail"):
                detail = l["detail"]
                if len(detail) > 200:
                    detail = detail[:197] + "..."
                rprint(f"  {detail}")
            if l.get("components"):
                comps = l["components"]
                if isinstance(comps, list):
                    rprint(f"  [dim]Components: {', '.join(comps)}[/dim]")
            if l.get("session_date"):
                rprint(f"  [dim]Date: {l['session_date']}[/dim]")
            rprint("")

    finally:
        conn.close()

@app.command()
def consolidate(
    min_learnings: int = typer.Option(2, "--min", "-m", help="Minimum learnings per entity to consider"),
    auto_accept: bool = typer.Option(False, "--yes", "-y", help="Accept all proposals without prompting"),
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Promote recurring learnings into decisions.

    Finds clusters of learnings sharing the same entity and uses an LLM to
    determine if they collectively represent an engineering decision worth
    documenting. Proposed decisions are shown interactively for acceptance.
    """
    config = Config.load()
    if not config.anthropic_api_key:
        rprint("[red]ANTHROPIC_API_KEY not set[/red]")
        raise typer.Exit(1)

    db = Path(db_path)
    if not db.exists():
        rprint(f"[red]Database not found at {db}. Run 'setkontext extract' first.[/red]")
        raise typer.Exit(1)

    conn = get_connection(db)
    repo_store = Repository(conn)

    try:
        # Step 1: Find clusters
        clusters = repo_store.get_learning_clusters(min_count=min_learnings)

        if not clusters:
            rprint("[yellow]No learning clusters found.[/yellow]")
            rprint("Clusters form when multiple learnings share the same entity.")
            rprint("Keep using setkontext and learnings will accumulate over time.")
            raise typer.Exit(0)

        rprint(f"[bold]Found {len(clusters)} entity cluster(s) with {min_learnings}+ learnings[/bold]\n")

        for c in clusters:
            existing = f" ({c['existing_decision_count']} existing decision(s))" if c["existing_decision_count"] else ""
            rprint(f"  [cyan]{c['entity']}[/cyan]: {c['learning_count']} learnings{existing}")

        rprint("")

        # Step 2: Analyze clusters with LLM
        anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        ) as progress:
            task = progress.add_task("Analyzing clusters for decision patterns...", total=len(clusters))

            proposals = find_consolidation_proposals(clusters, anthropic_client)
            progress.update(task, advance=len(clusters))

        if not proposals:
            rprint("[green]No learnings warrant promotion to decisions at this time.[/green]")
            rprint("This is normal — not every learning cluster represents a decision.")
            raise typer.Exit(0)

        # Step 3: Present proposals for acceptance
        rprint(f"\n[bold]{len(proposals)} decision proposal(s):[/bold]\n")

        accepted = 0
        rejected = 0
        repo_name = config.repo or "local"

        for i, proposal in enumerate(proposals, 1):
            d = proposal.decision
            rprint(f"[bold]Proposal {i}/{len(proposals)}[/bold]")
            rprint(f"  [green bold]{d.summary}[/green bold]")
            rprint(f"  [dim]Reasoning:[/dim] {d.reasoning}")
            if d.alternatives:
                rprint(f"  [dim]Alternatives:[/dim] {', '.join(d.alternatives)}")
            entities_str = ", ".join(e.name for e in d.entities)
            rprint(f"  [dim]Entities:[/dim] {entities_str}")
            rprint(f"  [dim]Confidence:[/dim] {d.confidence}")
            rprint(f"  [dim]Based on:[/dim] {len(proposal.source_learning_ids)} learning(s)")
            if proposal.rationale:
                rprint(f"  [dim]Rationale:[/dim] {proposal.rationale}")
            rprint("")

            if auto_accept:
                accept = True
            else:
                accept = typer.confirm("  Accept this decision?", default=True)

            if accept:
                source = create_consolidation_source(proposal, repo_name)
                repo_store.save_extraction_result(source, [d])
                accepted += 1
                rprint(f"  [green]Saved.[/green]\n")
            else:
                rejected += 1
                rprint(f"  [yellow]Skipped.[/yellow]\n")

        # Summary
        rprint(f"[bold]Consolidation complete:[/bold] {accepted} accepted, {rejected} skipped")

        if accepted > 0:
            rprint("\nNew decisions are now available via MCP tools and CLI queries.")
            rprint("Run [bold]setkontext generate[/bold] to update your CLAUDE.md context file.")
    finally:
        conn.close()


@app.command()
def check(
    days: int = typer.Option(30, help="How many days back to check for drift"),
    db_path: str = typer.Option("setkontext.db", help="Database file path"),
) -> None:
    """Check recent PRs for decisions that conflict with existing ones."""
    config = Config.load()
    issues = config.validate()
    if issues:
        for issue in issues:
            rprint(f"[red]Config error: {issue}[/red]")
        raise typer.Exit(1)

    since = datetime.now() - timedelta(days=days)
    rprint(f"[bold]Checking PRs merged since {since.date()} for decision drift...[/bold]")

    client = GitHubClient(token=config.github_token, repo=config.repo)
    fetcher = Fetcher(client)
    prs = fetcher.fetch_merged_prs(since=since)
    rprint(f"Found [bold]{len(prs)}[/bold] PRs to check")
    client.close()

    if not prs:
        rprint("[green]No recent PRs to check.[/green]")
        raise typer.Exit(0)

    # Set up validator with existing decisions
    db = Path(db_path)
    if not db.exists():
        rprint(f"[red]Database not found at {db}. Run 'setkontext extract' first.[/red]")
        raise typer.Exit(1)

    conn = get_connection(db)
    repo_store = Repository(conn)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    validator = DecisionValidator(repo_store, anthropic_client)

    conflicts_found = 0

    try:
        for pr in prs:
            # Build a description of what this PR did
            approach = f"PR #{pr.number}: {pr.title}\n{pr.body or ''}"
            context = f"Changed files: {', '.join(pr.changed_files[:10])}"

            result = validator.validate(approach, context)

            if result.verdict == "CONFLICTS":
                conflicts_found += 1
                rprint(f"\n[red bold]CONFLICT[/red bold] PR #{pr.number}: {pr.title}")
                rprint(f"  [dim]{pr.url}[/dim]")
                for c in result.conflicts:
                    rprint(f"  [red]- {c.explanation}[/red]")
                    rprint(f"    [dim]Decision: {c.decision_summary}[/dim]")
            elif result.verdict == "ALIGNS":
                rprint(f"[green]OK[/green] PR #{pr.number}: {pr.title}")
            else:
                rprint(f"[dim]--[/dim] PR #{pr.number}: {pr.title} [dim](no coverage)[/dim]")

        # Summary
        rprint(f"\n[bold]Done.[/bold] Checked {len(prs)} PRs, found {conflicts_found} conflict(s).")
        if conflicts_found > 0:
            rprint("[yellow]Review the conflicts above — these PRs may drift from existing decisions.[/yellow]")
    finally:
        conn.close()


if __name__ == "__main__":
    app()
