"""Orchestrates fetching PRs and ADR files from GitHub."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from github.ContentFile import ContentFile
from github.GithubException import GithubException, UnknownObjectException
from github.PullRequest import PullRequest

from setkontext.github.client import GitHubClient

# Common ADR directory paths to search
ADR_PATHS = [
    "docs/adr",
    "docs/decisions",
    "docs/architectural-decisions",
    "adr",
]

# Broader doc directories that may contain decision-rich content
DOC_PATHS = [
    "docs",
    "doc",
    "documentation",
]

# Root-level files that often contain architectural decisions
ROOT_DOC_NAMES = [
    "architecture.md",
    "design.md",
    "decisions.md",
    "technical-design.md",
    "tech-stack.md",
]


@dataclass
class PRData:
    """Raw PR data ready for decision extraction."""

    number: int
    title: str
    body: str
    url: str
    merged_at: str  # ISO format date
    review_comments: list[str]
    commit_messages: list[str]


@dataclass
class ADRData:
    """Raw ADR file data ready for parsing."""

    path: str
    content: str
    url: str


class Fetcher:
    """Fetches PRs and ADR files from a GitHub repository."""

    def __init__(self, client: GitHubClient) -> None:
        self._client = client

    def fetch_merged_prs(
        self, since: datetime | None = None, limit: int = 100
    ) -> list[PRData]:
        """Fetch merged PRs with their review comments and commit messages.

        Args:
            since: Only fetch PRs merged after this date. If None, fetches recent PRs.
            limit: Maximum number of PRs to fetch.
        """
        repo = self._client.repo
        pulls = repo.get_pulls(state="closed", sort="updated", direction="desc")

        results: list[PRData] = []
        for pr in pulls:
            if len(results) >= limit:
                break

            if not pr.merged:
                continue

            if since and pr.merged_at and pr.merged_at < since:
                break  # PRs are sorted by update time, so we can stop

            results.append(self._extract_pr_data(pr))

        return results

    def fetch_adrs(self, extra_paths: list[str] | None = None) -> list[ADRData]:
        """Find and fetch ADR markdown files from the repository.

        Searches common ADR directories and any extra paths provided.
        """
        search_paths = ADR_PATHS + (extra_paths or [])
        repo = self._client.repo
        results: list[ADRData] = []
        seen_paths: set[str] = set()

        # Search known directories
        for dir_path in search_paths:
            try:
                contents = repo.get_contents(dir_path)
            except (UnknownObjectException, GithubException):
                continue  # Directory doesn't exist, skip

            if not isinstance(contents, list):
                contents = [contents]

            for item in contents:
                if self._is_adr_file(item) and item.path not in seen_paths:
                    seen_paths.add(item.path)
                    adr = self._fetch_adr_content(item)
                    if adr:
                        results.append(adr)

        # Also search repo root for files with "adr" in the name
        try:
            root_contents = repo.get_contents("")
            if isinstance(root_contents, list):
                for item in root_contents:
                    if (
                        self._is_adr_file(item)
                        and "adr" in item.name.lower()
                        and item.path not in seen_paths
                    ):
                        seen_paths.add(item.path)
                        adr = self._fetch_adr_content(item)
                        if adr:
                            results.append(adr)
        except GithubException:
            pass

        return results

    def fetch_docs(self) -> list[ADRData]:
        """Find and fetch general documentation markdown files.

        Searches docs directories and root-level architecture files.
        Excludes files already found by fetch_adrs() — call that first.
        Returns ADRData (same shape, different source_type handled upstream).
        """
        repo = self._client.repo
        results: list[ADRData] = []
        seen_paths: set[str] = set()

        # Search doc directories
        for dir_path in DOC_PATHS:
            try:
                contents = repo.get_contents(dir_path)
            except (UnknownObjectException, GithubException):
                continue

            if not isinstance(contents, list):
                contents = [contents]

            for item in contents:
                if self._is_markdown_file(item) and item.path not in seen_paths:
                    seen_paths.add(item.path)
                    doc = self._fetch_adr_content(item)
                    if doc:
                        results.append(doc)

        # Search root for known architecture/design doc names
        try:
            root_contents = repo.get_contents("")
            if isinstance(root_contents, list):
                for item in root_contents:
                    if (
                        self._is_markdown_file(item)
                        and item.name.lower() in ROOT_DOC_NAMES
                        and item.path not in seen_paths
                    ):
                        seen_paths.add(item.path)
                        doc = self._fetch_adr_content(item)
                        if doc:
                            results.append(doc)
        except GithubException:
            pass

        return results

    def _is_markdown_file(self, item: ContentFile) -> bool:
        """Check if a GitHub content item is a markdown file."""
        if item.type != "file":
            return False
        name = item.name.lower()
        return name.endswith(".md") or name.endswith(".markdown")

    def _extract_pr_data(self, pr: PullRequest) -> PRData:
        """Extract relevant data from a PyGithub PullRequest object."""
        # Get review comments (limit to avoid huge payloads)
        review_comments: list[str] = []
        try:
            for comment in pr.get_review_comments():
                if len(review_comments) >= 20:
                    break
                if comment.body:
                    review_comments.append(comment.body)
        except GithubException:
            pass

        # Also get issue comments (top-level PR discussion)
        try:
            for comment in pr.get_issue_comments():
                if len(review_comments) >= 30:
                    break
                if comment.body:
                    review_comments.append(comment.body)
        except GithubException:
            pass

        # Get commit messages
        commit_messages: list[str] = []
        try:
            for commit in pr.get_commits():
                if len(commit_messages) >= 20:
                    break
                msg = commit.commit.message
                if msg:
                    commit_messages.append(msg)
        except GithubException:
            pass

        merged_at = ""
        if pr.merged_at:
            merged_at = pr.merged_at.isoformat()

        return PRData(
            number=pr.number,
            title=pr.title or "",
            body=pr.body or "",
            url=pr.html_url,
            merged_at=merged_at,
            review_comments=review_comments,
            commit_messages=commit_messages,
        )

    def _is_adr_file(self, item: ContentFile) -> bool:
        """Check if a GitHub content item looks like an ADR file."""
        return self._is_markdown_file(item)

    def _fetch_adr_content(self, item: ContentFile) -> ADRData | None:
        """Fetch the decoded content of an ADR file."""
        try:
            content = item.decoded_content
            if content is None:
                return None
            return ADRData(
                path=item.path,
                content=content.decode("utf-8"),
                url=item.html_url,
            )
        except (GithubException, UnicodeDecodeError):
            return None
