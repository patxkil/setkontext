"""Tests for setkontext.config."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from setkontext.config import DEFAULT_ADR_PATHS, DEFAULT_DB_PATH, Config


class TestConfigDefaults:
    def test_default_values(self):
        config = Config()
        assert config.github_token == ""
        assert config.repo == ""
        assert config.anthropic_api_key == ""
        assert config.db_path == DEFAULT_DB_PATH
        assert config.adr_paths == list(DEFAULT_ADR_PATHS)

    def test_adr_paths_are_independent_copies(self):
        c1 = Config()
        c2 = Config()
        c1.adr_paths.append("custom/path")
        assert "custom/path" not in c2.adr_paths


class TestConfigLoad:
    def test_load_from_env(self):
        env = {
            "SETKONTEXT_GITHUB_TOKEN": "ghp_test123",
            "SETKONTEXT_REPO": "acme/webapp",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "SETKONTEXT_DB_PATH": "/tmp/test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            config = Config.load()
        assert config.github_token == "ghp_test123"
        assert config.repo == "acme/webapp"
        assert config.anthropic_api_key == "sk-ant-test"
        assert config.db_path == Path("/tmp/test.db")

    def test_load_defaults_when_env_empty(self):
        env_keys = [
            "SETKONTEXT_GITHUB_TOKEN",
            "SETKONTEXT_REPO",
            "ANTHROPIC_API_KEY",
            "SETKONTEXT_DB_PATH",
        ]
        cleaned = {k: v for k, v in os.environ.items() if k not in env_keys}
        with patch.dict(os.environ, cleaned, clear=True):
            config = Config.load()
        assert config.github_token == ""
        assert config.repo == ""
        assert config.anthropic_api_key == ""
        assert config.db_path == DEFAULT_DB_PATH


class TestConfigValidate:
    def test_validate_all_missing(self):
        config = Config()
        issues = config.validate()
        assert len(issues) == 3
        assert any("GitHub token" in i for i in issues)
        assert any("Repository" in i for i in issues)
        assert any("Anthropic" in i for i in issues)

    def test_validate_all_present(self):
        config = Config(
            github_token="ghp_xxx",
            repo="acme/webapp",
            anthropic_api_key="sk-ant-xxx",
        )
        assert config.validate() == []

    def test_validate_partial(self):
        config = Config(github_token="ghp_xxx")
        issues = config.validate()
        assert len(issues) == 2
        assert not any("GitHub token" in i for i in issues)
