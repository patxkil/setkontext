"""Thin wrapper around PyGithub for authenticated GitHub API access."""

from __future__ import annotations

from github import Auth, Github
from github.Repository import Repository


class GitHubClient:
    """Authenticated GitHub client scoped to a single repository.

    Usage:
        client = GitHubClient(token="ghp_...", repo="owner/repo")
        repo = client.repo  # PyGithub Repository object
    """

    def __init__(self, token: str, repo: str) -> None:
        self._gh = Github(auth=Auth.Token(token))
        self._repo_name = repo
        self._repo: Repository | None = None

    @property
    def repo(self) -> Repository:
        if self._repo is None:
            self._repo = self._gh.get_repo(self._repo_name)
        return self._repo

    def close(self) -> None:
        self._gh.close()
