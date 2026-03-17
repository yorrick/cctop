import json
import os
from datetime import timedelta
from pathlib import Path

from cctop.models import Event
from cctop.sources.merger import SessionManager


def _write_session_file(sessions_dir: Path, pid: int, session_id: str, cwd: str) -> None:
    data = {"pid": pid, "sessionId": session_id, "cwd": cwd, "startedAt": 1773764468081}
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
            Event(ts=1000, sid="abc-123", type="tool_start", tool="Bash", cwd="/tmp/test"),
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
