"""Activity logging for MCP tool calls.

Logs every MCP tool invocation to a JSONL file so humans can see what
context their AI agent received from setkontext. Each line is a JSON object
with timestamp, tool name, arguments, result preview, and duration.

The log file lives alongside setkontext.db by default.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

RESULT_PREVIEW_LIMIT = 500


def _resolve_log_path() -> Path:
    """Find the log file path, checking env var then defaulting next to the DB."""
    env_path = os.getenv("SETKONTEXT_LOG_PATH")
    if env_path:
        return Path(env_path)

    # Default: same directory as the DB
    db_path = os.getenv("SETKONTEXT_DB_PATH", "setkontext.db")
    return Path(db_path).parent / "setkontext-activity.jsonl"


def log_tool_call(
    tool_name: str,
    arguments: dict,
    result_text: str,
    error: str | None,
    duration_ms: int,
) -> None:
    """Append a tool call entry to the activity log. Never raises."""
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "arguments": arguments,
            "result_preview": result_text[:RESULT_PREVIEW_LIMIT] if result_text else "",
            "error": error,
            "duration_ms": duration_ms,
        }
        log_path = _resolve_log_path()
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass  # Never crash the MCP server for logging


def read_activity_log(
    limit: int = 20,
    tool_name: str | None = None,
    log_path: Path | None = None,
) -> list[dict]:
    """Read recent activity log entries.

    Returns entries in reverse chronological order (most recent first).
    """
    path = log_path or _resolve_log_path()
    if not path.exists():
        return []

    entries: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if tool_name and entry.get("tool_name") != tool_name:
            continue

        entries.append(entry)

    # Most recent first, limited
    entries.reverse()
    return entries[:limit]
