import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cctop.models import Event, Session
from cctop.sources.index import IndexEntry, _read_transcript_metadata, encode_cwd, find_index_entry
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
        # Reverse mapping: PID-file session ID -> hook/transcript session ID
        self._pid_sid_to_hook_sid: dict[str, str] = {}
        # Maps cwd -> PID-file session ID for reverse lookup
        self._cwd_to_pid_sid: dict[str, str] = {}
        # Sessions that received a Stop event (Claude finished its turn).
        # Only these are candidates for idle transition after grace period.
        # Sessions with only tool_end events stay "working" (Claude is still thinking).
        self._stopped_sessions: set[str] = set()
        # Sessions not found in PID files on the last refresh — we give them
        # one extra refresh cycle before marking offline to avoid flicker
        # caused by transient file-read failures.
        self._missing_pids: dict[str, datetime] = {}

    @property
    def projects_dir(self) -> Path:
        return self._projects_dir

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
                    pr_url=existing.pr_url if existing else None,
                    pr_title=existing.pr_title if existing else None,
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
                    pr_url=existing.pr_url if existing else None,
                    pr_title=existing.pr_title if existing else None,
                )

            if session.status == "offline" and self._recent == timedelta(0):
                self._sessions.pop(raw.session_id, None)
                continue

            # Try index lookup with PID-file session ID first, then fall back
            # to the hook/transcript session ID (for resumed/continued sessions
            # where the PID file has a different ID than the transcript).
            entry = find_index_entry(self._projects_dir, raw.cwd, raw.session_id)
            if not entry:
                # Try 1: use known hook-to-PID mapping (learned from events)
                hook_sid = self._pid_sid_to_hook_sid.get(raw.session_id)
                if hook_sid:
                    entry = find_index_entry(self._projects_dir, raw.cwd, hook_sid)
            if not entry:
                # Try 2: find the active transcript by looking for the most recently
                # modified .jsonl in the project dir that was written to after this
                # session started. This handles pre-hook sessions safely.
                entry = _find_active_transcript_entry(
                    self._projects_dir,
                    raw.cwd,
                    raw.session_id,
                    raw.started_at,
                )
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

        # Apply idle grace period: only transition to idle if Claude has finished
        # its turn (Stop event received) AND the grace period has elapsed.
        # Sessions between tool calls (no Stop) stay "working".
        for session in self._sessions.values():
            if (
                session.status == "working"
                and session.session_id in self._stopped_sessions
                and (now - session.last_activity).total_seconds() > IDLE_GRACE_SECONDS
            ):
                session.status = "idle"
                self._stopped_sessions.discard(session.session_id)

        for sid in list(self._sessions.keys()):
            if sid not in seen_ids:
                session = self._sessions[sid]
                if session.status != "offline":
                    # Give one extra refresh cycle before marking offline to
                    # avoid flicker from transient PID-file read failures.
                    if sid not in self._missing_pids:
                        self._missing_pids[sid] = now
                        continue
                    session.status = "offline"
                    session.ended_at = now
                    self._sessions[sid] = session
                    self._missing_pids.pop(sid, None)

                if self._recent == timedelta(0):
                    del self._sessions[sid]
                elif session.ended_at and (now - session.ended_at) > self._recent:
                    del self._sessions[sid]
            else:
                # Session reappeared — clear any missing-pid tracking
                self._missing_pids.pop(sid, None)

    def _resolve_session(self, event: Event, allow_cwd_mapping: bool = True) -> Session | None:
        """Resolve a hook event to a Session, handling the session ID mismatch.

        When Claude resumes a session, the PID file gets a new session ID, but hooks
        still report the original transcript session ID. We resolve this by:
        1. Direct lookup (hook sid == pid-file sid, for sessions started after install)
        2. Cached mapping (we've seen this hook sid before and mapped it)
        3. CWD-based mapping (hook event cwd matches an active session's cwd)
           Only used for tool_start/tool_end/stop — not session_start/session_end,
           which can fire from transient subprocesses (e.g. `claude --print` spawned
           by generate_summary) that share the same cwd but are not the real session.
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
        if allow_cwd_mapping and event.cwd:
            pid_sid = self._cwd_to_pid_sid.get(event.cwd)
            if pid_sid:
                self._hook_sid_to_pid_sid[event.sid] = pid_sid
                self._pid_sid_to_hook_sid[pid_sid] = event.sid
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
            # session_start/session_end can fire from transient subprocesses (e.g.
            # `claude --print` spawned by generate_summary). Only allow CWD-based
            # resolution for events that indicate real Claude Code work activity.
            allow_cwd = event.type in ("tool_start", "tool_end", "stop")
            session = self._resolve_session(event, allow_cwd_mapping=allow_cwd)
            if session is None:
                continue

            now_ts = datetime.fromtimestamp(event.ts / 1000, tz=timezone.utc)

            match event.type:
                case "tool_start":
                    session.status = "working"
                    session.current_tool = event.tool
                    session.last_activity = now_ts
                    # New tool call means Claude is active again
                    self._stopped_sessions.discard(session.session_id)
                case "tool_end":
                    # Tool finished but Claude may call another — stay working
                    session.current_tool = None
                    session.last_activity = now_ts
                case "stop":
                    # Claude finished its turn — candidate for idle after grace period
                    session.current_tool = None
                    session.last_activity = now_ts
                    self._stopped_sessions.add(session.session_id)
                case "session_end":
                    # Only mark offline if the process is actually dead.
                    # session_end also fires on /clear, which resets the
                    # conversation but keeps the process alive.
                    from cctop.sources.sessions import is_pid_alive

                    if not is_pid_alive(session.pid):
                        session.status = "offline"
                        session.ended_at = now_ts
                    session.last_activity = now_ts
                    self._stopped_sessions.discard(session.session_id)
                case "session_start":
                    session.last_activity = now_ts
                    self._stopped_sessions.discard(session.session_id)


def _find_active_transcript_entry(
    projects_dir: Path,
    cwd: Path,
    session_id: str,
    started_at: datetime,
) -> IndexEntry | None:
    """Find the active transcript for a session by looking at recently modified files.

    When Claude resumes a session, the PID file gets a new session ID but the transcript
    stays under the original ID. We find it by looking for .jsonl files in the project
    directory that were modified after this session started.

    Safety: only returns a match if the most recent transcript was modified within
    5 minutes of the session start or later.
    """
    encoded = encode_cwd(cwd)
    project_dir = projects_dir / encoded

    if not project_dir.is_dir():
        return None

    # Find transcripts modified after this session started
    started_ts = started_at.timestamp()
    candidates: list[Path] = []
    for t in project_dir.glob("*.jsonl"):
        if t.stat().st_mtime >= started_ts - 300:  # 5 minute buffer before start
            candidates.append(t)

    if not candidates:
        return None

    # Pick the most recently modified one
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    best = candidates[0]

    # Don't use this transcript if its session ID matches the PID-file session ID
    # (that case is already handled by the direct lookup)
    if best.stem == session_id:
        return None

    return _read_transcript_metadata(session_id, best)


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
