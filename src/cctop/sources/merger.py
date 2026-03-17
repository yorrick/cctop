import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cctop.models import Event, Session
from cctop.sources.index import find_index_entry
from cctop.sources.sessions import discover_sessions

# Grace period before a session transitions from "working" to "idle".
# Claude thinks between tool calls, and users type prompts — neither should
# instantly flip to idle.
IDLE_GRACE_SECONDS = 30


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
        # Maps hook session IDs (transcript IDs) to PID-file session IDs.
        # When Claude resumes a session, the PID file gets a new session ID,
        # but hooks still report the original transcript session ID.
        self._hook_sid_to_pid_sid: dict[str, str] = {}
        # Maps cwd -> PID-file session ID for reverse lookup
        self._cwd_to_pid_sid: dict[str, str] = {}

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
            self._cwd_to_pid_sid[str(raw.cwd)] = raw.session_id

        # Apply idle grace period: if a session is "working" but has no current tool
        # and last_activity was more than IDLE_GRACE_SECONDS ago, transition to idle.
        for session in self._sessions.values():
            if (
                session.status == "working"
                and session.current_tool is None
                and (now - session.last_activity).total_seconds() > IDLE_GRACE_SECONDS
            ):
                session.status = "idle"

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

    def _resolve_session(self, event: Event) -> Session | None:
        """Resolve a hook event to a Session, handling the session ID mismatch.

        When Claude resumes a session, the PID file gets a new session ID, but hooks
        still report the original transcript session ID. We resolve this by:
        1. Direct lookup (hook sid == pid-file sid, for sessions started after install)
        2. Cached mapping (we've seen this hook sid before and mapped it)
        3. CWD-based mapping (hook event cwd matches an active session's cwd)
        """
        # Direct match
        session = self._sessions.get(event.sid)
        if session is not None:
            return session

        # Cached mapping
        pid_sid = self._hook_sid_to_pid_sid.get(event.sid)
        if pid_sid:
            return self._sessions.get(pid_sid)

        # CWD-based mapping: match hook event's cwd to a known session
        if event.cwd:
            pid_sid = self._cwd_to_pid_sid.get(event.cwd)
            if pid_sid:
                self._hook_sid_to_pid_sid[event.sid] = pid_sid
                # Also use the hook sid (transcript sid) for index lookups
                session = self._sessions.get(pid_sid)
                if session and not session.summary:
                    entry = find_index_entry(self._projects_dir, session.cwd, event.sid)
                    if entry:
                        session.summary = entry.summary
                        session.first_prompt = entry.first_prompt
                        if entry.git_branch:
                            session.git_branch = entry.git_branch
                        session.message_count = entry.message_count
                return session

        return None

    def apply_events(self, events: list[Event]) -> None:
        """Apply hook events to update session status."""
        for event in events:
            session = self._resolve_session(event)
            if session is None:
                continue

            now_ts = datetime.fromtimestamp(event.ts / 1000, tz=timezone.utc)

            match event.type:
                case "tool_start":
                    session.status = "working"
                    session.current_tool = event.tool
                    session.last_activity = now_ts
                case "tool_end" | "stop":
                    # Don't immediately flip to idle — keep "working" status
                    # and let the grace period in refresh() handle the transition.
                    # Just clear the current tool and update last_activity.
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
