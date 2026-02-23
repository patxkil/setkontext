"""Configuration loading for setkontext.

Config sources (in priority order):
1. Explicit arguments passed to functions
2. Environment variables (SETKONTEXT_GITHUB_TOKEN, etc.)
3. .env file in current directory
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = Path("setkontext.db")
DEFAULT_ADR_PATHS = [
    "docs/adr",
    "docs/decisions",
    "docs/architectural-decisions",
    "adr",
]


@dataclass
class Config:
    github_token: str = ""
    repo: str = ""  # "owner/repo"
    anthropic_api_key: str = ""
    db_path: Path = DEFAULT_DB_PATH
    adr_paths: list[str] = field(default_factory=lambda: list(DEFAULT_ADR_PATHS))

    @classmethod
    def load(cls) -> Config:
        return cls(
            github_token=os.getenv("SETKONTEXT_GITHUB_TOKEN", ""),
            repo=os.getenv("SETKONTEXT_REPO", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            db_path=Path(os.getenv("SETKONTEXT_DB_PATH", str(DEFAULT_DB_PATH))),
        )

    def validate(self) -> list[str]:
        """Return a list of missing config issues."""
        issues = []
        if not self.github_token:
            issues.append("GitHub token not set (SETKONTEXT_GITHUB_TOKEN)")
        if not self.repo:
            issues.append("Repository not set (SETKONTEXT_REPO)")
        if not self.anthropic_api_key:
            issues.append("Anthropic API key not set (ANTHROPIC_API_KEY)")
        return issues
