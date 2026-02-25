"""Tests for setkontext.activity — logging and reading."""

from __future__ import annotations

import json
from pathlib import Path

from setkontext.activity import log_tool_call, read_activity_log


class TestLogToolCall:
    def test_creates_log_file(self, tmp_path: Path):
        log_path = tmp_path / "activity.jsonl"
        # Temporarily override the log path via env
        import os
        old = os.environ.get("SETKONTEXT_LOG_PATH")
        os.environ["SETKONTEXT_LOG_PATH"] = str(log_path)
        try:
            log_tool_call("query_decisions", {"question": "Why X?"}, "answer", None, 100)
            assert log_path.exists()
            entry = json.loads(log_path.read_text().strip())
            assert entry["tool_name"] == "query_decisions"
            assert entry["arguments"]["question"] == "Why X?"
            assert entry["duration_ms"] == 100
            assert entry["error"] is None
        finally:
            if old is None:
                del os.environ["SETKONTEXT_LOG_PATH"]
            else:
                os.environ["SETKONTEXT_LOG_PATH"] = old

    def test_logs_error(self, tmp_path: Path):
        log_path = tmp_path / "activity.jsonl"
        import os
        old = os.environ.get("SETKONTEXT_LOG_PATH")
        os.environ["SETKONTEXT_LOG_PATH"] = str(log_path)
        try:
            log_tool_call("bad_tool", {}, "", "something broke", 50)
            entry = json.loads(log_path.read_text().strip())
            assert entry["error"] == "something broke"
        finally:
            if old is None:
                del os.environ["SETKONTEXT_LOG_PATH"]
            else:
                os.environ["SETKONTEXT_LOG_PATH"] = old

    def test_truncates_result_preview(self, tmp_path: Path):
        log_path = tmp_path / "activity.jsonl"
        import os
        old = os.environ.get("SETKONTEXT_LOG_PATH")
        os.environ["SETKONTEXT_LOG_PATH"] = str(log_path)
        try:
            long_result = "x" * 1000
            log_tool_call("tool", {}, long_result, None, 10)
            entry = json.loads(log_path.read_text().strip())
            assert len(entry["result_preview"]) == 500
        finally:
            if old is None:
                del os.environ["SETKONTEXT_LOG_PATH"]
            else:
                os.environ["SETKONTEXT_LOG_PATH"] = old


class TestReadActivityLog:
    def test_read_empty(self, tmp_path: Path):
        log_path = tmp_path / "missing.jsonl"
        entries = read_activity_log(log_path=log_path)
        assert entries == []

    def test_read_entries(self, tmp_path: Path):
        log_path = tmp_path / "activity.jsonl"
        for i in range(5):
            line = json.dumps({
                "timestamp": f"2024-01-01T00:00:0{i}",
                "tool_name": "query_decisions",
                "arguments": {},
                "result_preview": f"result {i}",
                "error": None,
                "duration_ms": i * 10,
            })
            with open(log_path, "a") as f:
                f.write(line + "\n")

        entries = read_activity_log(log_path=log_path)
        assert len(entries) == 5
        # Most recent first
        assert entries[0]["result_preview"] == "result 4"

    def test_filter_by_tool_name(self, tmp_path: Path):
        log_path = tmp_path / "activity.jsonl"
        for tool in ["query_decisions", "validate_approach", "query_decisions"]:
            line = json.dumps({
                "timestamp": "2024-01-01",
                "tool_name": tool,
                "arguments": {},
                "result_preview": "",
                "error": None,
                "duration_ms": 0,
            })
            with open(log_path, "a") as f:
                f.write(line + "\n")

        entries = read_activity_log(tool_name="query_decisions", log_path=log_path)
        assert len(entries) == 2

    def test_respects_limit(self, tmp_path: Path):
        log_path = tmp_path / "activity.jsonl"
        for i in range(10):
            line = json.dumps({
                "timestamp": f"2024-01-01T00:00:{i:02d}",
                "tool_name": "tool",
                "arguments": {},
                "result_preview": "",
                "error": None,
                "duration_ms": 0,
            })
            with open(log_path, "a") as f:
                f.write(line + "\n")

        entries = read_activity_log(limit=3, log_path=log_path)
        assert len(entries) == 3
