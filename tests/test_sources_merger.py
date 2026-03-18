import json
import os
from datetime import timedelta
from pathlib import Path

from cctop.models import Event
from cctop.sources.merger import SessionManager

# Default startedAt for test sessions — use _SESSION_STARTED_AT + offset for event timestamps
_SESSION_STARTED_AT = 1773764468081


def _write_session_file(
    sessions_dir: Path, pid: int, session_id: str, cwd: str, started_at: int = _SESSION_STARTED_AT
) -> None:
    data = {"pid": pid, "sessionId": session_id, "cwd": cwd, "startedAt": started_at}
    (sessions_dir / f"{pid}.json").write_text(json.dumps(data))


def test_merge_discovers_sessions(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    assert len(mgr.sessions) == 1
    assert mgr.sessions[0].session_id == "abc-123"
    assert mgr.sessions[0].status == "idle"


def test_merge_marks_dead_pid_offline(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, 99999999, "dead-session", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    assert len(mgr.sessions) == 0


def test_merge_applies_tool_events(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    mgr.apply_events(
        [
            Event(ts=1000, sid="abc-123", type="tool_start", tool="Bash"),
        ]
    )

    assert mgr.sessions[0].status == "working"
    assert mgr.sessions[0].current_tool == "Bash"


def test_merge_recent_zero_evicts_offline(tmp_path: Path) -> None:
    """With --recent 0 (default), dead PID sessions should not appear."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, 99999999, "dead-session", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
        recent=timedelta(0),
    )
    mgr.refresh()

    assert len(mgr.sessions) == 0


def test_merge_enriches_from_index(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    index_dir = projects_dir / "-tmp-test"
    index_dir.mkdir()
    index_data = {
        "version": 1,
        "originalPath": "/tmp/test",
        "entries": [
            {
                "sessionId": "abc-123",
                "summary": "Working on tests",
                "firstPrompt": "write tests",
                "gitBranch": "feat/tests",
                "messageCount": 10,
                "created": "2026-01-01T00:00:00.000Z",
                "modified": "2026-01-01T01:00:00.000Z",
                "projectPath": "/tmp/test",
                "isSidechain": False,
            }
        ],
    }
    (index_dir / "sessions-index.json").write_text(json.dumps(index_data))

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    assert mgr.sessions[0].summary == "Working on tests"
    assert mgr.sessions[0].git_branch == "feat/tests"
    assert mgr.sessions[0].message_count == 10


def test_merge_enriches_name_from_transcript(tmp_path: Path) -> None:
    """Session.name is populated from customTitle in the transcript."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    project_dir = projects_dir / "-tmp-test"
    project_dir.mkdir()
    transcript = project_dir / "abc-123.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "my-feature", "sessionId": "abc-123"})
        + "\n"
        + json.dumps({"type": "user", "message": {"content": "hello"}})
        + "\n"
    )

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    assert mgr.sessions[0].name == "my-feature"


def test_name_survives_refresh(tmp_path: Path) -> None:
    """Session.name set from transcript must persist across refresh() calls."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    project_dir = projects_dir / "-tmp-test"
    project_dir.mkdir()
    transcript = project_dir / "abc-123.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "my-feature", "sessionId": "abc-123"})
        + "\n"
        + json.dumps({"type": "user", "message": {"content": "hello"}})
        + "\n"
    )

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()
    assert mgr.sessions[0].name == "my-feature"

    # Second refresh: name must survive even if transcript is not re-read
    mgr.refresh()
    assert mgr.sessions[0].name == "my-feature"


def test_missing_pid_file_grace_period(tmp_path: Path) -> None:
    """Session stays alive for one refresh cycle if PID file temporarily disappears."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
        recent=timedelta(hours=1),
    )
    mgr.refresh()
    assert mgr.sessions[0].status == "idle"

    # Remove the PID file (simulating a transient read failure)
    (sessions_dir / f"{os.getpid()}.json").unlink()

    # First refresh after disappearance: session should still be idle (grace period)
    mgr.refresh()
    assert len(mgr.sessions) == 1
    assert mgr.sessions[0].status == "idle"

    # Second refresh: now it should be offline
    mgr.refresh()
    assert len(mgr.sessions) == 1
    assert mgr.sessions[0].status == "offline"


def test_missing_pid_file_reappears(tmp_path: Path) -> None:
    """Session recovers if PID file reappears within the grace period."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
        recent=timedelta(hours=1),
    )
    mgr.refresh()
    assert mgr.sessions[0].status == "idle"

    # Remove and immediately recreate
    (sessions_dir / f"{os.getpid()}.json").unlink()
    mgr.refresh()  # Grace period starts
    assert mgr.sessions[0].status == "idle"

    # File comes back
    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")
    mgr.refresh()
    assert mgr.sessions[0].status == "idle"  # Still alive, not offline


def test_pr_data_survives_refresh(tmp_path: Path) -> None:
    """PR URL and title set on a session must persist across refresh() cycles."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    # Simulate _poll_slow setting PR data on the session object
    mgr.sessions[0].pr_url = "https://github.com/org/repo/pull/42"
    mgr.sessions[0].pr_title = "feat: cool feature"

    # Next fast refresh recreates Session objects — PR data must survive
    mgr.refresh()

    assert mgr.sessions[0].pr_url == "https://github.com/org/repo/pull/42"
    assert mgr.sessions[0].pr_title == "feat: cool feature"


def test_transcript_path_mapping_resolves_resumed_session(tmp_path: Path) -> None:
    """Events with a different SID resolve via transcript_path matching."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "pid-sid-A", "/tmp/unique")

    # Create the project dir that encode_cwd("/tmp/unique") produces
    project_dir = projects_dir / "-tmp-unique"
    project_dir.mkdir()

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    # Event from a resumed session: different SID, but transcript_path
    # points to the same project directory as the session's CWD.
    transcript_path = str(project_dir / "hook-sid.jsonl")
    mgr.apply_events(
        [
            Event(
                ts=_SESSION_STARTED_AT + 1000,
                sid="hook-sid",
                type="tool_start",
                tool="Read",
                transcript_path=transcript_path,
            )
        ]
    )

    session = mgr.sessions[0]
    assert session.status == "working"
    assert session.current_tool == "Read"


def test_transcript_path_mapping_rejects_stale_events(tmp_path: Path) -> None:
    """Events older than the session's startedAt must not be mapped to it."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "new-session", "/tmp/test")

    project_dir = projects_dir / "-tmp-test"
    project_dir.mkdir()

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    # Stale event from an old session — timestamp before the current session started
    transcript_path = str(project_dir / "old-hook-sid.jsonl")
    mgr.apply_events(
        [
            Event(
                ts=_SESSION_STARTED_AT - 1000,
                sid="old-hook-sid",
                type="tool_start",
                tool="Bash",
                transcript_path=transcript_path,
            )
        ]
    )

    # Session should NOT have been affected
    session = mgr.sessions[0]
    assert session.status == "idle"
    assert session.current_tool is None


def test_events_without_transcript_path_only_resolve_by_sid(tmp_path: Path) -> None:
    """Events without transcript_path can only resolve via direct SID or cached mapping."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "session-A", "/tmp/test")

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    # Event with unknown SID and no transcript_path — should NOT resolve
    mgr.apply_events([Event(ts=_SESSION_STARTED_AT + 1000, sid="unknown-sid", type="tool_start", tool="Bash")])

    session = mgr.sessions[0]
    assert session.status == "idle"
    assert session.current_tool is None


def test_session_start_with_transcript_path_enriches_name(tmp_path: Path) -> None:
    """session_start event with transcript_path reads name from transcript."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "pid-sid", "/tmp/test")

    # Create a transcript at an arbitrary path with a custom-title
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "my-feature", "sessionId": "pid-sid"})
        + "\n"
        + json.dumps({"type": "user", "message": {"content": "hello"}})
        + "\n"
    )

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    assert mgr.sessions[0].name is None  # No transcript match by session ID

    # session_start event carries transcript_path — should enrich name
    mgr.apply_events(
        [
            Event(
                ts=1000,
                sid="pid-sid",
                type="session_start",
                cwd="/tmp/test",
                transcript_path=str(transcript),
            ),
        ]
    )

    assert mgr.sessions[0].name == "my-feature"


def test_session_start_without_transcript_path_no_crash(tmp_path: Path) -> None:
    """session_start without transcript_path still works normally."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    mgr.apply_events(
        [
            Event(ts=1000, sid="abc-123", type="session_start", cwd="/tmp/test"),
        ]
    )

    assert mgr.sessions[0].name is None


def test_cached_mapping_persists_after_transcript_path_match(tmp_path: Path) -> None:
    """Once transcript_path establishes a mapping, subsequent events use the cache."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "pid-sid", "/tmp/myproject")

    project_dir = projects_dir / "-tmp-myproject"
    project_dir.mkdir()

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    transcript_path = str(project_dir / "hook-sid.jsonl")

    # First event establishes the mapping via transcript_path
    mgr.apply_events(
        [
            Event(
                ts=_SESSION_STARTED_AT + 1000,
                sid="hook-sid",
                type="tool_start",
                tool="Bash",
                transcript_path=transcript_path,
            )
        ]
    )
    assert mgr.sessions[0].status == "working"

    # Second event from same hook SID — resolves via cached mapping,
    # even without transcript_path
    mgr.apply_events(
        [
            Event(
                ts=_SESSION_STARTED_AT + 2000,
                sid="hook-sid",
                type="stop",
            )
        ]
    )
    assert mgr.sessions[0].session_id in mgr._stopped_sessions  # noqa: SLF001


def test_refresh_retries_transcript_enrichment(tmp_path: Path) -> None:
    """If transcript wasn't ready during session_start, refresh() retries."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "pid-sid", "/tmp/test")

    project_dir = projects_dir / "-tmp-test"
    project_dir.mkdir()
    transcript = project_dir / "pid-sid.jsonl"

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    # session_start fires but transcript doesn't exist yet
    mgr.apply_events(
        [
            Event(
                ts=_SESSION_STARTED_AT + 100,
                sid="pid-sid",
                type="session_start",
                transcript_path=str(transcript),
            ),
        ]
    )
    assert mgr.sessions[0].name is None

    # Now the transcript appears (simulating Claude Code writing it)
    transcript.write_text(json.dumps({"type": "custom-title", "customTitle": "backlog", "sessionId": "pid-sid"}) + "\n")

    # Next refresh() should pick up the name via the stored transcript_path
    mgr.refresh()
    assert mgr.sessions[0].name == "backlog"
