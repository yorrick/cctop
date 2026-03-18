from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, computed_field, model_validator


class Event(BaseModel):
    """A single hook event from events.jsonl."""

    ts: int
    sid: str
    type: Literal["tool_start", "tool_end", "stop", "session_start", "session_end"]
    tool: str | None = None
    ok: bool | None = None
    cwd: str | None = None


class Session(BaseModel):
    """A Claude Code session with merged data from all sources."""

    session_id: str
    pid: int
    cwd: Path
    project_name: str
    worktree_name: str | None = None
    git_branch: str | None = None
    pr_url: str | None = None
    pr_title: str | None = None
    status: Literal["working", "idle", "offline"]
    current_tool: str | None = None
    started_at: datetime
    last_activity: datetime
    ended_at: datetime | None = None
    message_count: int = 0
    summary: str | None = None
    name: str | None = None
    first_prompt: str | None = None

    @model_validator(mode="after")
    def _extract_worktree_info(self) -> "Session":
        """Extract worktree name and fix project name for worktree paths.

        For a path like /Users/foo/work/project/.worktrees/dev-loop/issue-349:
        - worktree_name = "issue-349" (last segment)
        - project_name = "project" (directory before .worktrees)
        """
        parts = self.cwd.parts
        for i, part in enumerate(parts):
            if part in ("worktrees", ".worktrees") and i + 1 < len(parts):
                self.worktree_name = parts[-1] if len(parts) > i + 2 else parts[i + 1]
                # Derive project name from the parent of the worktrees directory
                if i > 0:
                    self.project_name = parts[i - 1]
                break
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def idle_duration(self) -> timedelta:
        """Compute idle duration based on status."""
        match self.status:
            case "working":
                return timedelta(0)
            case "idle":
                return datetime.now(tz=timezone.utc) - self.last_activity
            case "offline":
                if self.ended_at:
                    return self.ended_at - self.last_activity
                return timedelta(0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def session_duration(self) -> timedelta:
        """Compute total session duration."""
        if self.status == "offline" and self.ended_at:
            return self.ended_at - self.started_at
        return datetime.now(tz=timezone.utc) - self.started_at
