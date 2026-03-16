"""Smart PR filtering to skip PRs unlikely to contain engineering decisions.

Filters are heuristic-based (no LLM calls) and designed to reduce extraction
cost by ~50% by skipping bot PRs, trivial changes, and docs-only updates.
"""

from __future__ import annotations

from dataclasses import dataclass

from setkontext.github.fetcher import PRData

# Known bot account logins (case-insensitive comparison)
BOT_AUTHORS = frozenset({
    "dependabot",
    "dependabot[bot]",
    "renovate",
    "renovate[bot]",
    "github-actions",
    "github-actions[bot]",
    "greenkeeper[bot]",
    "snyk-bot",
    "codecov[bot]",
    "sonarcloud[bot]",
    "mergify[bot]",
    "allcontributors[bot]",
    "pre-commit-ci[bot]",
    "depfu[bot]",
    "imgbot[bot]",
    "stale[bot]",
    "release-please[bot]",
})

# Title patterns that indicate low-decision-value PRs
SKIP_TITLE_PATTERNS = (
    "bump ",
    "chore(deps)",
    "chore: bump",
    "chore: update",
    "update dependency",
    "upgrade dependency",
    "lock file maintenance",
    "auto-merge",
    "release v",
    "release:",
    "prepare release",
    "version bump",
)

# File extensions that are unlikely to contain engineering decisions
NON_DECISION_EXTENSIONS = frozenset({
    ".md", ".markdown", ".rst", ".txt",       # docs
    ".json", ".yaml", ".yml", ".toml",         # config
    ".lock", ".sum",                            # lockfiles
    ".png", ".jpg", ".jpeg", ".gif", ".svg",   # images
    ".ico", ".webp",
    ".gitignore", ".gitattributes",            # git meta
    ".editorconfig",                            # editor meta
})

# File paths that are non-decision by nature
NON_DECISION_PATHS = (
    ".github/",
    ".vscode/",
    ".idea/",
    "examples/",
    "example/",
    "__snapshots__/",
)

# Minimum word count in PR body to consider it worth analyzing
MIN_BODY_WORDS = 10


@dataclass
class FilterResult:
    """Result of a PR filter check."""

    skip: bool
    reason: str  # empty if not skipped


def should_skip(pr: PRData) -> FilterResult:
    """Check if a PR should be skipped for decision extraction.

    Returns a FilterResult indicating whether to skip and why.
    All checks are heuristic — no LLM calls.
    """
    # 1. Bot author check
    if _is_bot(pr):
        return FilterResult(skip=True, reason="bot-authored")

    # 2. Title-based skip (dependency bumps, releases, etc.)
    title_lower = pr.title.lower().strip()
    for pattern in SKIP_TITLE_PATTERNS:
        if title_lower.startswith(pattern):
            return FilterResult(skip=True, reason=f"title-pattern:{pattern.strip()}")

    # 3. Empty or trivially short body with no review discussion
    body_words = len(pr.body.split()) if pr.body else 0
    has_review_content = any(len(c.split()) > 20 for c in pr.review_comments)
    if body_words < MIN_BODY_WORDS and not has_review_content:
        return FilterResult(skip=True, reason="empty-body")

    # 4. Non-decision file changes only
    if pr.changed_files and _all_non_decision_files(pr.changed_files):
        return FilterResult(skip=True, reason="non-decision-files-only")

    return FilterResult(skip=False, reason="")


def _is_bot(pr: PRData) -> bool:
    """Check if the PR author is a bot."""
    if pr.author_type == "Bot":
        return True
    if pr.author.lower() in BOT_AUTHORS:
        return True
    # Catch [bot] suffix pattern for any author
    if pr.author.endswith("[bot]"):
        return True
    return False


def _all_non_decision_files(changed_files: list[str]) -> bool:
    """Check if ALL changed files are non-decision types (docs, config, images)."""
    if not changed_files:
        return False  # No file info — don't skip

    for filepath in changed_files:
        lower = filepath.lower()

        # Check path prefixes
        if any(lower.startswith(prefix) for prefix in NON_DECISION_PATHS):
            continue

        # Check extensions
        has_non_decision_ext = any(lower.endswith(ext) for ext in NON_DECISION_EXTENSIONS)
        if has_non_decision_ext:
            continue

        # This file looks like it could contain real code changes
        return False

    return True
