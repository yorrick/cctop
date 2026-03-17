import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cctop.models import Event, Session
from cctop.sources.index import find_index_entry
from cctop.sources.sessions import discover_sessions


class SessionManager:
    """Merges all data sources into a list of Session objects."""

    def __init__(
        self,
        sessions_dir: Path | None = None,
        projects_dir: Path | None = None,
        recent: timedelta = timedelta(0),
    ) -> None:
        self._sessions_dir = sessions_dir or Path.home() / ".claude" / "sessions"
        self._projects_dir = projects_dir or Path.home() / ".claude" / "projects"
        self._recent = recent
        self._sessions: dict[str, Session] = {}

    @property
    def sessions(self) -> list[Session]:
        """Return sessions sorted by status (working first, then idle, then offline)."""
        return list(self._sessions.values())

    def refresh(self) -> None:
        """Re-discover sessions and enrich with index data."""
        raw_sessions = discover_sessions(self._sessions_dir)
        now = datetime.now(tz=timezone.utc)

        seen_ids: set[str] = set()
        for raw in raw_sessions:
            seen_ids.add(raw.session_id)
            existing = self._sessions.get(raw.session_id)

            if raw.is_alive:
                status = existing.status if existing and existing.status == "working" else "idle"
                current_tool = existing.current_tool if existing and status == "working" else None
                last_activity = existing.last_activity if existing else raw.started_at

                session = Session(
                    session_id=raw.session_id,
                    pid=raw.pid,
                    cwd=raw.cwd,
                    project_name=raw.cwd.name or str(raw.cwd),
                    status=status,
                    current_tool=current_tool,
                    started_at=raw.started_at,
                    last_activity=last_activity,
                )
            else:
                ended_at = existing.ended_at if existing else now
                last_activity = existing.last_activity if existing else raw.started_at

                session = Session(
                    session_id=raw.session_id,
                    pid=raw.pid,
                    cwd=raw.cwd,
                    project_name=raw.cwd.name or str(raw.cwd),
                    status="offline",
                    started_at=raw.started_at,
                    last_activity=last_activity,
                    ended_at=ended_at,
                )

            if session.status == "offline" and self._recent == timedelta(0):
                self._sessions.pop(raw.session_id, None)
                continue

            entry = find_index_entry(self._projects_dir, raw.cwd, raw.session_id)
            if entry:
                session.summary = entry.summary
                session.first_prompt = entry.first_prompt
                session.git_branch = entry.git_branch
                session.message_count = entry.message_count

            # If no git branch from index, detect from the working directory
            if not session.git_branch:
                session.git_branch = _detect_git_branch(raw.cwd)

            self._sessions[raw.session_id] = session

        for sid in list(self._sessions.keys()):
            if sid not in seen_ids:
                session = self._sessions[sid]
                if session.status != "offline":
                    session.status = "offline"
                    session.ended_at = now
                    self._sessions[sid] = session

                if self._recent == timedelta(0):
                    del self._sessions[sid]
                elif session.ended_at and (now - session.ended_at) > self._recent:
                    del self._sessions[sid]

    def apply_events(self, events: list[Event]) -> None:
        """Apply hook events to update session status."""
        for event in events:
            session = self._sessions.get(event.sid)
            if session is None:
                continue

            now_ts = datetime.fromtimestamp(event.ts / 1000, tz=timezone.utc)

            match event.type:
                case "tool_start":
                    session.status = "working"
                    session.current_tool = event.tool
                    session.last_activity = now_ts
                case "tool_end" | "stop":
                    session.status = "idle"
                    session.current_tool = None
                    session.last_activity = now_ts
                case "session_end":
                    session.status = "offline"
                    session.ended_at = now_ts
                    session.last_activity = now_ts
                case "session_start":
                    session.last_activity = now_ts


_git_branch_cache: dict[str, str | None] = {}


def _detect_git_branch(cwd: Path) -> str | None:
    """Detect the current git branch for a working directory."""
    cwd_str = str(cwd)
    if cwd_str in _git_branch_cache:
        return _git_branch_cache[cwd_str]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            _git_branch_cache[cwd_str] = branch
            return branch
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    _git_branch_cache[cwd_str] = None
    return None
