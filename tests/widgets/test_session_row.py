from datetime import datetime, timezone
from pathlib import Path

from cctop.models import Session
from cctop.widgets.session_row import SessionRow


def _make_session(name: str | None = None) -> Session:
    return Session(
        session_id="abc-123",
        pid=12345,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="idle",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_activity=datetime(2026, 1, 1, tzinfo=timezone.utc),
        name=name,
    )


def test_session_row_shows_name_when_set() -> None:
    session = _make_session("my-feature")
    row = SessionRow(session)
    rendered = row.render().plain
    assert "my-feature" in rendered


def test_session_row_shows_dash_when_name_none() -> None:
    session = _make_session(None)
    row = SessionRow(session)
    rendered = row.render().plain
    # The NAME column should show the em-dash placeholder
    assert "—" in rendered


def test_session_row_truncates_long_name() -> None:
    session = _make_session("a" * 20)
    row = SessionRow(session)
    rendered = row.render().plain
    # Should be truncated: first 15 chars + ellipsis
    assert "aaaaaaaaaaaaaaa…" in rendered
    # The full 20-char name should NOT appear
    assert "a" * 20 not in rendered
