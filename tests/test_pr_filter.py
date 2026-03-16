"""Tests for smart PR filtering."""

from __future__ import annotations

from setkontext.github.fetcher import PRData
from setkontext.github.filter import FilterResult, should_skip


def _make_pr(**overrides) -> PRData:
    """Create a PRData with sensible defaults, overridable for each test."""
    defaults = dict(
        number=1,
        title="Add user authentication with JWT",
        body="We chose JWT over session cookies because our API is consumed by mobile clients that need stateless auth.",
        url="https://github.com/acme/app/pull/1",
        merged_at="2024-06-15T10:00:00",
        review_comments=[],
        commit_messages=["Implement JWT auth middleware"],
        changed_files=["src/auth/jwt.py", "src/auth/middleware.py"],
        author="engineer",
        author_type="User",
        labels=[],
    )
    defaults.update(overrides)
    return PRData(**defaults)


class TestBotFiltering:
    def test_skip_dependabot(self):
        pr = _make_pr(author="dependabot[bot]", author_type="Bot")
        result = should_skip(pr)
        assert result.skip is True
        assert result.reason == "bot-authored"

    def test_skip_renovate(self):
        pr = _make_pr(author="renovate[bot]", author_type="Bot")
        result = should_skip(pr)
        assert result.skip is True

    def test_skip_by_author_type_bot(self):
        pr = _make_pr(author="some-unknown-bot[bot]", author_type="Bot")
        result = should_skip(pr)
        assert result.skip is True

    def test_skip_bot_suffix_even_without_type(self):
        pr = _make_pr(author="custom-ci[bot]", author_type="User")
        result = should_skip(pr)
        assert result.skip is True

    def test_keep_human_author(self):
        pr = _make_pr(author="engineer", author_type="User")
        result = should_skip(pr)
        assert result.skip is False


class TestTitleFiltering:
    def test_skip_dependency_bump(self):
        pr = _make_pr(title="bump fastapi from 0.95 to 0.100")
        result = should_skip(pr)
        assert result.skip is True
        assert "title-pattern" in result.reason

    def test_skip_chore_deps(self):
        pr = _make_pr(title="chore(deps): update dependency lodash")
        result = should_skip(pr)
        assert result.skip is True

    def test_skip_release(self):
        pr = _make_pr(title="release v2.3.0")
        result = should_skip(pr)
        assert result.skip is True

    def test_keep_meaningful_title(self):
        pr = _make_pr(title="Migrate from REST to gRPC for internal services")
        result = should_skip(pr)
        assert result.skip is False

    def test_keep_title_with_bump_in_middle(self):
        """'bump' at start triggers skip, but in the middle should not."""
        pr = _make_pr(title="Fix version bump script for staging")
        result = should_skip(pr)
        assert result.skip is False


class TestBodyFiltering:
    def test_skip_empty_body(self):
        pr = _make_pr(body="", review_comments=[])
        result = should_skip(pr)
        assert result.skip is True
        assert result.reason == "empty-body"

    def test_skip_short_body(self):
        pr = _make_pr(body="fix typo", review_comments=[])
        result = should_skip(pr)
        assert result.skip is True

    def test_keep_short_body_with_review_discussion(self):
        """If the body is short but reviews have substance, keep it."""
        pr = _make_pr(
            body="fix typo",
            review_comments=[
                "Actually this changes the auth strategy. We discussed switching to "
                "OAuth2 because the JWT approach had issues with token revocation "
                "in the mobile app."
            ],
        )
        result = should_skip(pr)
        assert result.skip is False

    def test_keep_substantial_body(self):
        pr = _make_pr(
            body="We decided to switch from PostgreSQL to CockroachDB because "
                 "we need multi-region support and automatic sharding. The tradeoff "
                 "is higher operational complexity but we gain horizontal scalability."
        )
        result = should_skip(pr)
        assert result.skip is False


class TestFileFiltering:
    def test_skip_docs_only(self):
        pr = _make_pr(changed_files=["README.md", "docs/setup.md"])
        result = should_skip(pr)
        assert result.skip is True
        assert result.reason == "non-decision-files-only"

    def test_skip_config_only(self):
        pr = _make_pr(changed_files=[".github/workflows/ci.yml", "package.json"])
        result = should_skip(pr)
        assert result.skip is True

    def test_skip_images_only(self):
        pr = _make_pr(changed_files=["assets/logo.png", "docs/screenshot.jpg"])
        result = should_skip(pr)
        assert result.skip is True

    def test_keep_mixed_files(self):
        pr = _make_pr(changed_files=["README.md", "src/auth/jwt.py"])
        result = should_skip(pr)
        assert result.skip is False

    def test_keep_code_only(self):
        pr = _make_pr(changed_files=["src/main.py", "src/utils.py"])
        result = should_skip(pr)
        assert result.skip is False

    def test_keep_when_no_file_info(self):
        """If we don't have file info, don't skip — be conservative."""
        pr = _make_pr(changed_files=[])
        result = should_skip(pr)
        assert result.skip is False


class TestFilterPriority:
    """Verify filters apply in the right order (bot > title > body > files)."""

    def test_bot_takes_priority_over_good_body(self):
        pr = _make_pr(
            author="dependabot[bot]",
            author_type="Bot",
            title="Add new authentication strategy",
            body="Long detailed description of an architectural change...",
        )
        result = should_skip(pr)
        assert result.skip is True
        assert result.reason == "bot-authored"

    def test_title_takes_priority_over_good_files(self):
        pr = _make_pr(
            title="bump fastapi from 0.95 to 0.100",
            changed_files=["src/main.py"],
        )
        result = should_skip(pr)
        assert result.skip is True
        assert "title-pattern" in result.reason
