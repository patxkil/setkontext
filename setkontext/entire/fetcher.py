"""Fetches AI agent session data from Entire.io's git shadow branches.

Entire.io stores agent session transcripts on a special git branch
(entire/checkpoints/v1) in the target repository. Sessions are sharded
into directories by checkpoint ID: <id[:2]>/<id[2:]>/.

Each session directory contains:
  - metadata.json: session metadata (agent, branch, files, summary)
  - full.jsonl: complete transcript (user/assistant messages, tool uses)
  - prompt.txt: the initial user prompt
  - context.md: context that was loaded (optional)

We read these via `git show` so we don't need to check out the branch.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CHECKPOINT_BRANCH = "entire/checkpoints/v1"


@dataclass
class SessionData:
    """Raw session data ready for decision extraction."""

    session_id: str
    checkpoint_id: str
    agent: str  # e.g. "claude-code", "cursor"
    branch: str  # git branch the session was on
    prompt: str  # initial user prompt
    transcript: list[dict]  # parsed JSONL messages
    files_touched: list[str]
    summary: str  # Entire.io's summary of the session
    metadata: dict  # full metadata.json contents


@dataclass
class EntireFetcher:
    """Fetches session data from Entire.io's checkpoint branch in a local git repo."""

    repo_dir: Path

    def has_checkpoint_branch(self) -> bool:
        """Check if the entire/checkpoints/v1 branch exists locally or in remote."""
        # Check local branches
        result = self._git("branch", "--list", CHECKPOINT_BRANCH)
        if result and result.strip():
            return True

        # Check remote branches
        result = self._git("branch", "-r", "--list", f"*/{CHECKPOINT_BRANCH}")
        if result and result.strip():
            # Fetch it locally so git show works
            remote_ref = result.strip().split("\n")[0].strip()
            self._git("fetch", "origin", CHECKPOINT_BRANCH)
            return True

        return False

    def fetch_sessions(self, limit: int = 50) -> list[SessionData]:
        """Fetch session data from the checkpoint branch.

        Args:
            limit: Maximum number of sessions to fetch.
        """
        if not self.has_checkpoint_branch():
            logger.info("No entire/checkpoints/v1 branch found")
            return []

        # Use the remote ref if local doesn't exist
        ref = self._resolve_ref()
        if not ref:
            return []

        # List all checkpoint directories (sharded: XX/YYYYYYYYYY/)
        tree_output = self._git("ls-tree", "-r", "--name-only", ref)
        if not tree_output:
            return []

        # Find all session directories by looking for metadata.json files
        metadata_paths = [
            line for line in tree_output.strip().split("\n")
            if line.endswith("/metadata.json") or line.endswith("metadata.json")
        ]

        # Group by session directory (the directory containing metadata.json)
        session_dirs: list[str] = []
        for path in metadata_paths:
            # Path format: XX/YYYYYY/N/metadata.json (N is checkpoint number)
            # We want the parent dir of metadata.json
            parts = path.rsplit("/", 1)
            if parts:
                session_dirs.append(parts[0])

        # Deduplicate and limit
        seen: set[str] = set()
        unique_dirs: list[str] = []
        for d in session_dirs:
            if d not in seen:
                seen.add(d)
                unique_dirs.append(d)

        session_dirs = unique_dirs[:limit]
        logger.info(f"Found {len(session_dirs)} session checkpoints")

        sessions: list[SessionData] = []
        for session_dir in session_dirs:
            session = self._read_session(ref, session_dir)
            if session:
                sessions.append(session)

        return sessions

    def _resolve_ref(self) -> str | None:
        """Find the best git ref for the checkpoint branch."""
        # Try local branch first
        result = self._git("rev-parse", "--verify", CHECKPOINT_BRANCH)
        if result and result.strip():
            return CHECKPOINT_BRANCH

        # Try remote
        result = self._git("rev-parse", "--verify", f"origin/{CHECKPOINT_BRANCH}")
        if result and result.strip():
            return f"origin/{CHECKPOINT_BRANCH}"

        return None

    def _read_session(self, ref: str, session_dir: str) -> SessionData | None:
        """Read a single session's data from the git tree."""
        # Read metadata.json
        metadata_raw = self._git_show(ref, f"{session_dir}/metadata.json")
        if not metadata_raw:
            return None

        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse metadata for {session_dir}")
            return None

        # Read the transcript (full.jsonl)
        transcript_raw = self._git_show(ref, f"{session_dir}/full.jsonl")
        transcript: list[dict] = []
        if transcript_raw:
            for line in transcript_raw.strip().split("\n"):
                if line.strip():
                    try:
                        transcript.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Read the initial prompt
        prompt = self._git_show(ref, f"{session_dir}/prompt.txt") or ""

        # Extract fields from metadata
        session_id = metadata.get("SessionID", metadata.get("session_id", ""))
        checkpoint_id = self._extract_checkpoint_id(session_dir)
        agent = metadata.get("Agent", metadata.get("agent", "unknown"))
        branch = metadata.get("Branch", metadata.get("branch", ""))
        files_touched = metadata.get("FilesTouched", metadata.get("files_touched", []))
        summary = metadata.get("Summary", metadata.get("summary", ""))

        if not transcript and not prompt:
            logger.debug(f"Skipping empty session {session_dir}")
            return None

        return SessionData(
            session_id=session_id,
            checkpoint_id=checkpoint_id,
            agent=agent,
            branch=branch,
            prompt=prompt.strip(),
            transcript=transcript,
            files_touched=files_touched if isinstance(files_touched, list) else [],
            summary=summary,
            metadata=metadata,
        )

    def _extract_checkpoint_id(self, session_dir: str) -> str:
        """Extract checkpoint ID from the sharded directory path.

        Path format: XX/YYYYYYYYYY/N where XXYYYYYYYYYY is the 12-char checkpoint ID
        """
        parts = session_dir.split("/")
        if len(parts) >= 2:
            return parts[0] + parts[1]
        return session_dir

    def _git_show(self, ref: str, path: str) -> str | None:
        """Read a file from a git ref without checking out."""
        return self._git("show", f"{ref}:{path}")

    def _git(self, *args: str) -> str | None:
        """Run a git command in the repo directory."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
