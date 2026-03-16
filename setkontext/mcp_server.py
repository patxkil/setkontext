"""MCP server for setkontext.

Exposes engineering decisions to AI coding agents via the Model Context Protocol.
Agents can query decisions, search by entity, and get implementation guidance.

Usage:
    uv run python -m setkontext.mcp_server [--db /path/to/setkontext.db]

Configure in Claude Code (~/.claude.json):
    {
      "mcpServers": {
        "setkontext": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/setkontext", "python", "-m", "setkontext.mcp_server"]
        }
      }
    }

Configure in Cursor (settings → MCP):
    Same command, or use the .cursorrules static file as fallback.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import anthropic
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from setkontext.activity import log_tool_call
from setkontext.config import Config
from setkontext.context import generate_context
from setkontext.query.engine import QueryEngine
from setkontext.query.validator import DecisionValidator
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository

# Tiered context: L0 = summary only, L1 = truncated detail, L2 = full detail
L1_MAX_CHARS = 800

DETAIL_LEVEL_SCHEMA = {
    "type": "string",
    "enum": ["summary", "standard", "full"],
    "description": (
        "How much detail to return. "
        "'summary' = one-line summaries only (cheapest). "
        "'standard' = summaries + truncated reasoning (~800 chars). "
        "'full' = everything including full reasoning text. "
        "Default: standard."
    ),
}


def _shape_decision(d: dict, detail_level: str) -> dict:
    """Shape a decision dict based on the requested detail level."""
    if detail_level == "summary":
        return {
            k: v for k, v in d.items()
            if k in ("id", "summary", "confidence", "decision_date", "entities",
                      "source_url", "source_title", "source_type")
        }
    elif detail_level == "full":
        return d
    else:  # standard
        shaped = dict(d)
        if shaped.get("reasoning") and len(shaped["reasoning"]) > L1_MAX_CHARS:
            shaped["reasoning"] = shaped["reasoning"][:L1_MAX_CHARS] + "..."
        return shaped


def _shape_learning(l: dict, detail_level: str) -> dict:
    """Shape a learning dict based on the requested detail level."""
    if detail_level == "summary":
        return {
            k: v for k, v in l.items()
            if k in ("id", "summary", "category", "session_date", "entities",
                      "components", "source_url", "source_title", "source_type")
        }
    elif detail_level == "full":
        return l
    else:  # standard
        shaped = dict(l)
        if shaped.get("detail") and len(shaped["detail"]) > L1_MAX_CHARS:
            shaped["detail"] = shaped["detail"][:L1_MAX_CHARS] + "..."
        return shaped


def _shape_items(items: list[dict], detail_level: str) -> list[dict]:
    """Shape a list of decision or learning dicts."""
    result = []
    for item in items:
        if item.get("_type") == "learning" or "category" in item:
            result.append(_shape_learning(item, detail_level))
        else:
            result.append(_shape_decision(item, detail_level))
    return result


def _resolve_db_path() -> Path:
    """Find the database, checking CLI args, env var, then current directory."""
    # CLI arg: --db /path/to/db
    for i, arg in enumerate(sys.argv):
        if arg == "--db" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])

    # Env var
    env_db = os.getenv("SETKONTEXT_DB_PATH")
    if env_db:
        return Path(env_db)

    # Default: current directory
    return Path("setkontext.db")


DB_PATH = _resolve_db_path()

server = Server("setkontext")


def _get_repo() -> Repository:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found at {DB_PATH}. "
            "Run 'setkontext extract' first, or set SETKONTEXT_DB_PATH."
        )
    conn = get_connection(DB_PATH)
    return Repository(conn)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="query_decisions",
            description=(
                "Ask a question about engineering decisions in this codebase. "
                "Use this to understand WHY the system is built the way it is, "
                "or to get implementation guidance consistent with existing decisions. "
                "Works for 'why', 'how should I', and 'what' questions. "
                "Examples: 'why did we choose FastAPI?', 'how should I add a new endpoint?', "
                "'what database do we use?'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Your question about engineering decisions",
                    },
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="get_decisions_by_entity",
            description=(
                "Get all engineering decisions related to a specific technology, "
                "pattern, or service. Returns raw decision data with sources. "
                "Use list_entities first to see what's available."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Technology, pattern, or service name (e.g. 'PostgreSQL', 'FastAPI')",
                    },
                    "detail_level": DETAIL_LEVEL_SCHEMA,
                },
                "required": ["entity"],
            },
        ),
        types.Tool(
            name="validate_approach",
            description=(
                "IMPORTANT: Call this BEFORE implementing any significant technical choice. "
                "Validates whether a proposed approach conflicts with existing engineering decisions. "
                "Pass your intended approach (e.g., 'I plan to use Redis for caching' or "
                "'I will add a REST endpoint using Express') and get back whether it aligns with, "
                "conflicts with, or is not covered by team decisions. "
                "This prevents accidentally contradicting established architecture."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "proposed_approach": {
                        "type": "string",
                        "description": "What you plan to implement and how",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context: what feature/task this is for",
                    },
                },
                "required": ["proposed_approach"],
            },
        ),
        types.Tool(
            name="get_decision_context",
            description=(
                "Get the full engineering decisions context for this project. "
                "Returns a structured summary of all key decisions, tech stack, and patterns. "
                "Call this at the START of any implementation task to understand project constraints. "
                "Then use validate_approach before making specific technical choices."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="list_entities",
            description=(
                "List all technologies, patterns, and services that have engineering "
                "decisions. Shows decision counts per entity."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="recall_learnings",
            description=(
                "Search past session learnings — bugs solved, gotchas discovered, "
                "and features implemented. Use this before working in an area to "
                "avoid known pitfalls and leverage past solutions. "
                "Examples: 'authentication bugs', 'deployment gotchas', 'caching implementation'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["bug_fix", "gotcha", "implementation"],
                        "description": "Optional: filter by learning type",
                    },
                    "detail_level": DETAIL_LEVEL_SCHEMA,
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_related_entities",
            description=(
                "Find technologies and patterns related to a given entity. "
                "Shows what uses, depends on, replaces, or conflicts with it. "
                "Useful for understanding the technology graph around a component."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": "Entity name (e.g. 'fastapi', 'postgresql')",
                    },
                },
                "required": ["entity"],
            },
        ),
        types.Tool(
            name="get_session_briefing",
            description=(
                "Get a briefing of what happened in recent sessions. "
                "Call this at the START of a new session to catch up on: "
                "recent learnings, recurring patterns that may warrant decisions, "
                "and any new decisions. This prevents repeating past mistakes "
                "and keeps you aligned with the latest team knowledge."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback": {
                        "type": "integer",
                        "description": "Number of recent learnings to include (default: 10)",
                        "default": 10,
                    },
                },
            },
        ),
        types.Tool(
            name="get_context_for_file",
            description=(
                "Get decisions and learnings relevant to a specific file path. "
                "Use this when starting to work on a file to understand its history, "
                "past bugs, and architectural decisions that affect it."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path (e.g. 'src/auth/login.py')",
                    },
                    "detail_level": DETAIL_LEVEL_SCHEMA,
                },
                "required": ["file_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    start = time.time()
    result: list[types.TextContent] = []
    error: str | None = None
    try:
        result = _dispatch_tool(name, arguments)
        return result
    except FileNotFoundError as e:
        error = str(e)
        result = [types.TextContent(type="text", text=f"Setup required: {e}")]
        return result
    except Exception as e:
        error = str(e)
        result = [types.TextContent(type="text", text=f"Error: {e}")]
        return result
    finally:
        duration_ms = int((time.time() - start) * 1000)
        result_text = result[0].text if result else ""
        log_tool_call(name, arguments, result_text, error, duration_ms)


def _dispatch_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Route a tool call to the appropriate handler."""
    detail = arguments.get("detail_level", "standard")
    if name == "query_decisions":
        return _handle_query(arguments["question"])
    elif name == "validate_approach":
        return _handle_validate(
            arguments["proposed_approach"],
            arguments.get("context", ""),
        )
    elif name == "get_decisions_by_entity":
        return _handle_entity_query(arguments["entity"], detail)
    elif name == "get_decision_context":
        return _handle_full_context()
    elif name == "list_entities":
        return _handle_list_entities()
    elif name == "recall_learnings":
        return _handle_recall_learnings(
            arguments["query"],
            arguments.get("category"),
            detail,
        )
    elif name == "get_related_entities":
        return _handle_related_entities(arguments["entity"])
    elif name == "get_session_briefing":
        return _handle_session_briefing(arguments.get("lookback", 10))
    elif name == "get_context_for_file":
        return _handle_context_for_file(arguments["file_path"], detail)
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


def _handle_query(question: str) -> list[types.TextContent]:
    config = Config.load()
    if not config.anthropic_api_key:
        # Fall back to returning raw decisions without synthesis
        repo = _get_repo()
        engine = QueryEngine.__new__(QueryEngine)
        engine._repo = repo
        engine._client = None
        decisions = engine._find_relevant_decisions(question)
        if not decisions:
            return [types.TextContent(type="text", text="No relevant decisions found.")]
        result = {
            "question": question,
            "note": "Raw decisions returned (no ANTHROPIC_API_KEY for synthesis)",
            "decisions": decisions,
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    repo = _get_repo()
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    engine = QueryEngine(repo, client)
    result = engine.query(question)
    return [types.TextContent(type="text", text=result.to_json())]


def _handle_validate(proposed_approach: str, context: str) -> list[types.TextContent]:
    config = Config.load()
    if not config.anthropic_api_key:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "verdict": "NO_COVERAGE",
                "recommendation": "Cannot validate: ANTHROPIC_API_KEY not set. Proceed with caution.",
            }, indent=2),
        )]

    repo = _get_repo()
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    validator = DecisionValidator(repo, client)
    result = validator.validate(proposed_approach, context)
    return [types.TextContent(type="text", text=result.to_json())]


def _handle_entity_query(entity: str, detail_level: str = "standard") -> list[types.TextContent]:
    repo = _get_repo()
    decisions = repo.get_decisions_by_entity(entity)

    if not decisions:
        # Try case-insensitive partial match
        all_entities = repo.get_entities()
        suggestions = [
            e["entity"] for e in all_entities
            if entity.lower() in e["entity"].lower()
        ]
        msg = f"No decisions found for '{entity}'."
        if suggestions:
            msg += f" Did you mean: {', '.join(suggestions)}?"
        return [types.TextContent(type="text", text=msg)]

    result = {
        "entity": entity,
        "decision_count": len(decisions),
        "decisions": _shape_items(decisions, detail_level),
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


def _handle_full_context() -> list[types.TextContent]:
    repo = _get_repo()
    context = generate_context(repo, format="generic")
    return [types.TextContent(type="text", text=context)]


def _handle_list_entities() -> list[types.TextContent]:
    repo = _get_repo()
    entities = repo.get_entities()
    stats = repo.get_stats()
    result = {
        "total_decisions": stats["total_decisions"],
        "total_entities": len(entities),
        "entities": entities,
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


def _handle_recall_learnings(
    query: str, category: str | None, detail_level: str = "standard"
) -> list[types.TextContent]:
    repo = _get_repo()

    # Build FTS query (reuse same stop-word logic as QueryEngine)
    stop_words = {
        "why", "did", "we", "the", "a", "an", "is", "are", "was", "were",
        "do", "does", "how", "what", "when", "where", "which", "who",
        "our", "their", "this", "that", "for", "with", "from", "about",
        "use", "using", "used", "should", "would", "could",
        "have", "has", "had", "not", "and", "or", "but", "in", "on",
        "to", "of", "it", "its", "be", "been", "being",
    }
    words = []
    for word in query.lower().split():
        cleaned = "".join(c for c in word if c.isalnum())
        if cleaned and cleaned not in stop_words and len(cleaned) > 2:
            words.append(cleaned)

    fts_query = " OR ".join(words) if words else query

    learnings = repo.search_learnings(fts_query, category=category, limit=15)

    # Also try entity matching + graph-expanded search
    if len(learnings) < 5:
        seen_ids = {l["id"] for l in learnings}
        all_entities = repo.get_entities()
        query_lower = query.lower()
        matched_entities: list[str] = []
        for e in all_entities:
            if e["entity"] in query_lower:
                matched_entities.append(e["entity"])
                for l in repo.get_learnings_by_entity(e["entity"]):
                    if l["id"] not in seen_ids:
                        seen_ids.add(l["id"])
                        learnings.append(l)

        # Graph expansion: also search related entities
        for entity in matched_entities:
            related = repo.get_related_entities(entity, depth=1)
            for rel in related:
                for l in repo.get_learnings_by_entity(rel["entity"]):
                    if l["id"] not in seen_ids:
                        seen_ids.add(l["id"])
                        learnings.append(l)

    # Fall back to recent learnings if nothing found
    if not learnings:
        learnings = repo.get_recent_learnings(limit=10, category=category)

    if not learnings:
        return [types.TextContent(type="text", text="No learnings found. Sessions haven't been captured yet.")]

    result = {
        "query": query,
        "category_filter": category,
        "count": len(learnings),
        "learnings": _shape_items(learnings, detail_level),
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


def _handle_related_entities(entity: str) -> list[types.TextContent]:
    repo = _get_repo()
    related = repo.get_related_entities(entity, depth=2)

    if not related:
        return [types.TextContent(
            type="text",
            text=f"No relationships found for '{entity}'. "
            "Entity relationships are extracted during 'setkontext extract'.",
        )]

    result = {
        "entity": entity,
        "relationship_count": len(related),
        "relationships": related,
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


def _handle_session_briefing(lookback: int) -> list[types.TextContent]:
    repo = _get_repo()

    # Recent learnings
    recent_learnings = repo.get_recent_learnings(limit=lookback)

    # Learning clusters (potential decision candidates)
    clusters = repo.get_learning_clusters(min_count=2)

    # Recent decisions (added in last 7 days)
    from datetime import datetime, timedelta
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")
    recent_decisions = repo.get_decisions_in_range(week_ago, today)

    # Build briefing
    sections: list[str] = []

    if recent_learnings:
        lines = [f"## Recent Learnings ({len(recent_learnings)})"]
        for l in recent_learnings[:lookback]:
            cat = l.get("category", "unknown").replace("_", " ").upper()
            lines.append(f"- **[{cat}]** {l.get('summary', '')}")
        sections.append("\n".join(lines))

    if clusters:
        lines = ["## Recurring Patterns (consolidation candidates)"]
        lines.append("These entities appear in multiple learnings. Consider running "
                     "`setkontext consolidate` to promote them into decisions.")
        for c in clusters:
            existing = f" (already {c['existing_decision_count']} decision(s))" if c["existing_decision_count"] else ""
            lines.append(f"- **{c['entity']}**: {c['learning_count']} learnings{existing}")
        sections.append("\n".join(lines))

    if recent_decisions:
        lines = [f"## Recent Decisions ({len(recent_decisions)}, last 7 days)"]
        for d in recent_decisions:
            lines.append(f"- {d.get('summary', '')} [{d.get('confidence', '')}]")
        sections.append("\n".join(lines))

    if not sections:
        return [types.TextContent(
            type="text",
            text="No session history yet. Learnings will accumulate as you use setkontext.",
        )]

    briefing = "# Session Briefing\n\n" + "\n\n".join(sections)
    return [types.TextContent(type="text", text=briefing)]


def _handle_context_for_file(file_path: str, detail_level: str = "standard") -> list[types.TextContent]:
    repo = _get_repo()
    items = repo.get_items_by_file(file_path)

    if not items:
        return [types.TextContent(
            type="text",
            text=f"No decisions or learnings found for '{file_path}'. "
            "File references are populated during extraction from PR changed files "
            "and learning components.",
        )]

    decisions = [i for i in items if i.get("_type") == "decision"]
    learnings = [i for i in items if i.get("_type") == "learning"]

    result = {
        "file_path": file_path,
        "decision_count": len(decisions),
        "learning_count": len(learnings),
        "decisions": _shape_items(decisions, detail_level),
        "learnings": _shape_items(learnings, detail_level),
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
