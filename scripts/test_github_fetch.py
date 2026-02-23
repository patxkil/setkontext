"""Manual verification: test GitHub fetching against a real repo.

Usage:
    SETKONTEXT_GITHUB_TOKEN=ghp_... uv run python scripts/test_github_fetch.py owner/repo

Uses a public repo by default if no argument given.
"""

from __future__ import annotations

import sys

from setkontext.config import Config
from setkontext.github.client import GitHubClient
from setkontext.github.fetcher import Fetcher


def main() -> None:
    config = Config.load()

    # Allow repo override from CLI arg
    repo = sys.argv[1] if len(sys.argv) > 1 else config.repo
    token = config.github_token

    if not token:
        print("ERROR: Set SETKONTEXT_GITHUB_TOKEN environment variable")
        sys.exit(1)

    if not repo:
        print("ERROR: Provide repo as argument or set SETKONTEXT_REPO")
        sys.exit(1)

    print(f"Connecting to {repo}...")
    client = GitHubClient(token=token, repo=repo)

    try:
        fetcher = Fetcher(client)

        # Fetch PRs
        print("\n--- Merged PRs (last 5) ---")
        prs = fetcher.fetch_merged_prs(limit=5)
        for pr in prs:
            print(f"  #{pr.number}: {pr.title}")
            print(f"    Merged: {pr.merged_at}")
            print(f"    Body: {pr.body[:100]}..." if pr.body else "    Body: (empty)")
            print(f"    Review comments: {len(pr.review_comments)}")
            print(f"    Commits: {len(pr.commit_messages)}")
            print()

        # Fetch ADRs
        print("--- ADR Files ---")
        adrs = fetcher.fetch_adrs()
        if adrs:
            for adr in adrs:
                print(f"  {adr.path}")
                print(f"    URL: {adr.url}")
                print(f"    Content: {adr.content[:100]}...")
                print()
        else:
            print("  No ADR files found")

        print(f"\nSummary: {len(prs)} PRs, {len(adrs)} ADRs")

    finally:
        client.close()


if __name__ == "__main__":
    main()
