from datetime import datetime, timezone

from cctop.models import Session
from cctop.widgets.session_row import SessionRow


def _make_session(**kwargs) -> Session:
    defaults = {
        "session_id": "test-id",
        "pid": 1234,
        "cwd": "/tmp/test",
        "project_name": "test",
        "status": "idle",
        "started_at": datetime.now(tz=timezone.utc),
        "last_activity": datetime.now(tz=timezone.utc),
    }
    defaults.update(kwargs)
    return Session(**defaults)


def test_working_with_tool_shows_tool_name() -> None:
    session = _make_session(status="working", current_tool="Bash")
    row = SessionRow(session)
    text = row.render()
    assert "Working: Bash" in text.plain


def test_working_without_tool_shows_working_not_offline() -> None:
    """Regression: working + no current_tool must render 'Working', not 'Offline'."""
    session = _make_session(status="working", current_tool=None)
    row = SessionRow(session)
    text = row.render()
    assert "Working" in text.plain
    assert "Offline" not in text.plain


def test_idle_shows_idle() -> None:
    session = _make_session(status="idle")
    row = SessionRow(session)
    text = row.render()
    assert "Idle" in text.plain


def test_offline_shows_offline() -> None:
    session = _make_session(
        status="offline",
        ended_at=datetime.now(tz=timezone.utc),
    )
    row = SessionRow(session)
    text = row.render()
    assert "Offline" in text.plain
