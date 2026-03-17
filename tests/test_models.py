from datetime import datetime, timedelta, timezone
from pathlib import Path

from cctop.models import Event, Session


def test_session_idle_duration_when_working() -> None:
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="working",
        started_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.idle_duration == timedelta(0)


def test_session_idle_duration_when_idle() -> None:
    last = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="idle",
        started_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        last_activity=last,
    )
    assert s.idle_duration >= timedelta(minutes=4)


def test_session_idle_duration_when_offline() -> None:
    last = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    ended = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="offline",
        started_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        last_activity=last,
        ended_at=ended,
    )
    # Frozen at death time: ended_at - last_activity
    assert timedelta(minutes=4) <= s.idle_duration <= timedelta(minutes=6)


def test_session_duration_when_alive() -> None:
    start = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="idle",
        started_at=start,
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.session_duration >= timedelta(hours=1, minutes=59)


def test_session_duration_when_offline() -> None:
    start = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    ended = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="offline",
        started_at=start,
        last_activity=start,
        ended_at=ended,
    )
    assert timedelta(minutes=59) <= s.session_duration <= timedelta(hours=1, minutes=1)


def test_worktree_name_extracted() -> None:
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/Users/foo/work/project/.worktrees/dev-loop/issue-349"),
        project_name="project",
        status="idle",
        started_at=datetime.now(tz=timezone.utc),
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.worktree_name == "issue-349"


def test_worktree_name_none_for_regular_path() -> None:
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/Users/foo/work/project"),
        project_name="project",
        status="idle",
        started_at=datetime.now(tz=timezone.utc),
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.worktree_name is None


def test_event_tool_start() -> None:
    e = Event(ts=1000, sid="abc", type="tool_start", tool="Bash", cwd="/tmp")
    assert e.type == "tool_start"
    assert e.tool == "Bash"


def test_event_stop() -> None:
    e = Event(ts=1000, sid="abc", type="stop")
    assert e.tool is None
