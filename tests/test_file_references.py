"""Tests for file reference CRUD and lookup."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from setkontext.extraction.models import Decision, Entity, Learning, Source
from setkontext.storage.repository import Repository


class TestSaveFileReferences:
    def test_save_and_retrieve(
        self, repo: Repository, sample_source: Source, sample_decision: Decision,
    ):
        repo.save_extraction_result(sample_source, [sample_decision])
        repo.save_file_references("decision", sample_decision.id, ["src/api/main.py", "src/api/routes.py"])
        items = repo.get_items_by_file("src/api/main.py")
        assert len(items) == 1
        assert items[0]["_type"] == "decision"
        assert items[0]["summary"] == sample_decision.summary

    def test_prefix_match(
        self, repo: Repository, sample_source: Source, sample_decision: Decision,
    ):
        repo.save_extraction_result(sample_source, [sample_decision])
        repo.save_file_references("decision", sample_decision.id, ["src/api/main.py"])
        # Query with just the directory
        items = repo.get_items_by_file("src/api/")
        assert len(items) == 1

    def test_empty_paths_ignored(self, repo: Repository):
        repo.save_file_references("decision", "some-id", ["", "valid.py", ""])
        # Should not crash, empty paths silently ignored

    def test_no_results(self, repo: Repository):
        items = repo.get_items_by_file("nonexistent/file.py")
        assert items == []


class TestLearningComponentsAutoSaved:
    def test_components_saved_as_file_refs(
        self, repo: Repository, sample_learning_source: Source, sample_learning: Learning,
    ):
        """Learning.components should automatically create file_references."""
        repo.save_learning_result(sample_learning_source, [sample_learning])
        items = repo.get_items_by_file("auth/session.py")
        assert len(items) == 1
        assert items[0]["_type"] == "learning"
        assert items[0]["summary"] == sample_learning.summary

    def test_both_components_findable(
        self, repo: Repository, sample_learning_source: Source, sample_learning: Learning,
    ):
        repo.save_learning_result(sample_learning_source, [sample_learning])
        items1 = repo.get_items_by_file("auth/session.py")
        items2 = repo.get_items_by_file("auth/middleware.py")
        assert len(items1) == 1
        assert len(items2) == 1
