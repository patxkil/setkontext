"""Tests for incremental extraction watermarks."""

from __future__ import annotations

import json

from setkontext.storage.repository import Repository


class TestWatermarks:
    def test_get_nonexistent_returns_none(self, repo: Repository):
        assert repo.get_watermark("pr", "last_merged_at") is None

    def test_set_and_get(self, repo: Repository):
        repo.set_watermark("pr", "last_merged_at", "2024-06-15T10:00:00")
        assert repo.get_watermark("pr", "last_merged_at") == "2024-06-15T10:00:00"

    def test_update_overwrites(self, repo: Repository):
        repo.set_watermark("pr", "last_merged_at", "2024-06-15T10:00:00")
        repo.set_watermark("pr", "last_merged_at", "2024-07-01T12:00:00")
        assert repo.get_watermark("pr", "last_merged_at") == "2024-07-01T12:00:00"

    def test_different_source_types_independent(self, repo: Repository):
        repo.set_watermark("pr", "last_merged_at", "2024-06-15")
        repo.set_watermark("adr", "content_hashes", '{"docs/adr/001.md": "abc123"}')
        assert repo.get_watermark("pr", "last_merged_at") == "2024-06-15"
        assert repo.get_watermark("adr", "content_hashes") == '{"docs/adr/001.md": "abc123"}'

    def test_different_keys_independent(self, repo: Repository):
        repo.set_watermark("pr", "last_merged_at", "2024-06-15")
        repo.set_watermark("pr", "last_number", "42")
        assert repo.get_watermark("pr", "last_merged_at") == "2024-06-15"
        assert repo.get_watermark("pr", "last_number") == "42"

    def test_stores_json_content_hashes(self, repo: Repository):
        """Verify content hash watermarks round-trip through JSON."""
        hashes = {
            "docs/adr/001.md": "abc123def456",
            "docs/adr/002.md": "789ghi012jkl",
        }
        repo.set_watermark("adr", "content_hashes", json.dumps(hashes))
        result = json.loads(repo.get_watermark("adr", "content_hashes"))
        assert result == hashes


class TestWatermarkTable:
    def test_table_exists(self, db_conn):
        """Verify the watermarks table was created by schema migration."""
        row = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='watermarks'"
        ).fetchone()
        assert row is not None
