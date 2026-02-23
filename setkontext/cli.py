"""CLI entry point for setkontext."""

from __future__ import annotations

from pathlib import Path

import anthropic
import typer
from rich import print as rprint
from rich.progress import Progress, SpinnerColumn, TextColumn

from setkontext.config import Config
from setkontext.context import generate_context_file
from setkontext.extraction.adr import extract_adr_decisions
from setkontext.extraction.doc import extract_doc_decisions
from setkontext.extraction.pr import extract_pr_decisions
from setkontext.github.client import GitHubClient
from setkontext.github.fetcher import Fetcher
from setkontext.query.engine import QueryEngine
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
                },
            }
        }
    }

    mcp_config_path.write_text(json.dumps(config, indent=2) + "\n")
    rprint(f"MCP config written to {mcp_config_path}")


def _update_gitignore(project_dir: Path) -> None:
    """Ensure .gitignore includes setkontext files that shouldn't be committed."""
    gitignore_path = project_dir / ".gitignore"
    entries_to_add = ["setkontext.db", ".env"]

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
    _update_gitignore(project_dir)

    rprint(f"\n[green bold]setkontext initialized for {repo}[/green bold]")
    rprint("\nNext steps:")
    rprint("  1. Run [bold]setkontext extract[/bold] to pull decisions from GitHub")
    rprint("  2. Restart Claude Code — it picks up the MCP server automatically")
    rprint("  3. Your agent now has setkontext tools for querying decisions")


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

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        ) as progress:
            # Fetch and extract ADRs
            progress.add_task("Fetching ADR files...", total=None)
            adrs = fetcher.fetch_adrs()
            rprint(f"Found [bold]{len(adrs)}[/bold] ADR files")

            adr_decision_count = 0
            for adr in adrs:
                source, decisions = extract_adr_decisions(adr, config.repo)
                repo_store.save_extraction_result(source, decisions)
                adr_decision_count += len(decisions)

            rprint(f"Extracted [bold]{adr_decision_count}[/bold] decisions from ADRs")

            # Fetch and extract general documentation
            progress.add_task("Fetching documentation files...", total=None)
            docs = fetcher.fetch_docs()
            # Exclude files already processed as ADRs
            adr_paths = {adr.path for adr in adrs}
            docs = [d for d in docs if d.path not in adr_paths]
            rprint(f"Found [bold]{len(docs)}[/bold] documentation files")

            if docs:
                anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
                doc_decision_count = 0

                task = progress.add_task("Analyzing docs for decisions...", total=len(docs))
                for doc in docs:
                    rprint(f"  Analyzing {doc.path}...")
                    source, decisions = extract_doc_decisions(doc, config.repo, anthropic_client)
                    repo_store.save_extraction_result(source, decisions)
                    doc_decision_count += len(decisions)
                    rprint(f"    → [green]{len(decisions)} decision(s)[/green]")
                    progress.update(task, advance=1)

                rprint(f"Extracted [bold]{doc_decision_count}[/bold] decisions from docs")

            if not skip_prs:
                # Fetch PRs
                progress.add_task(f"Fetching up to {limit} merged PRs...", total=None)
                prs = fetcher.fetch_merged_prs(limit=limit)
                rprint(f"Found [bold]{len(prs)}[/bold] merged PRs")

                if prs:
                    # Extract decisions from PRs using Claude
                    if not docs:  # Only create client if not already created
                        anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)
                    pr_decision_count = 0
                    pr_with_decisions = 0

                    task = progress.add_task("Analyzing PRs for decisions...", total=len(prs))
                    for pr in prs:
                        source, decisions = extract_pr_decisions(pr, config.repo, anthropic_client)
                        repo_store.save_extraction_result(source, decisions)
                        if decisions:
                            pr_with_decisions += 1
                            pr_decision_count += len(decisions)
                            rprint(f"  PR #{pr.number}: [green]{len(decisions)} decision(s)[/green]")
                        progress.update(task, advance=1)

                    rprint(
                        f"Extracted [bold]{pr_decision_count}[/bold] decisions from "
                        f"[bold]{pr_with_decisions}[/bold] PRs "
                        f"({len(prs) - pr_with_decisions} PRs had no decisions)"
                    )

        # Print summary
        stats = repo_store.get_stats()
        rprint("\n[bold]Extraction complete:[/bold]")
        rprint(f"  Total decisions: {stats['total_decisions']}")
        rprint(f"  Unique entities: {stats['unique_entities']}")
        rprint(
            f"  Sources: {stats['pr_sources']} PRs, "
            f"{stats['adr_sources']} ADRs, "
            f"{stats.get('doc_sources', 0)} docs"
        )

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


if __name__ == "__main__":
    app()
