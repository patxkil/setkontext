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
from pathlib import Path

import anthropic
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from setkontext.config import Config
from setkontext.context import generate_context
from setkontext.query.engine import QueryEngine
from setkontext.storage.db import get_connection
from setkontext.storage.repository import Repository


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
                },
                "required": ["entity"],
            },
        ),
        types.Tool(
            name="get_decision_context",
            description=(
                "Get the full engineering decisions context for this project. "
                "Returns a structured summary of all key decisions, tech stack, and patterns. "
                "Call this at the START of any implementation task to understand project constraints."
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "query_decisions":
            return _handle_query(arguments["question"])
        elif name == "get_decisions_by_entity":
            return _handle_entity_query(arguments["entity"])
        elif name == "get_decision_context":
            return _handle_full_context()
        elif name == "list_entities":
            return _handle_list_entities()
        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    except FileNotFoundError as e:
        return [types.TextContent(type="text", text=f"Setup required: {e}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


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


def _handle_entity_query(entity: str) -> list[types.TextContent]:
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
        "decisions": decisions,
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
