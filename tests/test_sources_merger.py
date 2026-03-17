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
