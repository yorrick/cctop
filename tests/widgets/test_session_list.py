# tests/widgets/test_session_list.py
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.binding import Binding

from cctop.app import CctopApp
from cctop.models import Session
from cctop.widgets.session_list import SessionList


def _make_session(session_id: str = "abc-123", pid: int = 12345) -> Session:
    return Session(
        session_id=session_id,
        pid=pid,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="idle",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_activity=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_space_binding_maps_to_toggle_expand() -> None:
    """Verify Space is bound to action_toggle_expand."""
    bindings = {b.key: b.action for b in SessionList.BINDINGS if isinstance(b, Binding)}
    assert bindings["space"] == "toggle_expand"


def test_enter_binding_maps_to_focus_iterm() -> None:
    """Verify Enter is bound to action_focus_iterm."""
    bindings = {b.key: b.action for b in SessionList.BINDINGS if isinstance(b, Binding)}
    assert bindings["enter"] == "focus_iterm"


@pytest.mark.asyncio
async def test_action_focus_iterm_bridge_unavailable() -> None:
    """When iTerm2 bridge is not available, action_focus_iterm is a no-op."""
    widget = SessionList()
    widget._sessions = [_make_session()]
    widget._cursor = 0

    mock_bridge = MagicMock()
    mock_bridge.available = False

    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_bridge.activate_session.assert_not_called()


@pytest.mark.asyncio
async def test_action_focus_iterm_success_no_notification() -> None:
    """When activate_session returns True, no notification is shown."""
    widget = SessionList()
    widget._sessions = [_make_session()]
    widget._cursor = 0

    mock_bridge = MagicMock()
    mock_bridge.available = True
    mock_bridge.activate_session = AsyncMock(return_value=True)

    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_bridge.activate_session.assert_awaited_once_with(12345)
    mock_app.notify.assert_not_called()


@pytest.mark.asyncio
async def test_action_focus_iterm_no_match_shows_notification() -> None:
    """When activate_session returns False, a notification is shown."""
    widget = SessionList()
    widget._sessions = [_make_session()]
    widget._cursor = 0

    mock_bridge = MagicMock()
    mock_bridge.available = True
    mock_bridge.activate_session = AsyncMock(return_value=False)

    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_app.notify.assert_called_once_with("No iTerm2 pane found for this session")


@pytest.mark.asyncio
async def test_action_focus_iterm_empty_sessions() -> None:
    """When session list is empty, action_focus_iterm is a no-op."""
    widget = SessionList()
    widget._sessions = []

    mock_bridge = MagicMock()
    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_bridge.activate_session.assert_not_called()


@pytest.fixture
def mock_sessions(tmp_path: Path) -> tuple[Path, Path]:
    """Create mock Claude session files."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    data = {
        "pid": os.getpid(),
        "sessionId": "test-session-abc",
        "cwd": str(tmp_path),
        "startedAt": 1773764468081,
    }
    (sessions_dir / f"{os.getpid()}.json").write_text(json.dumps(data))

    return sessions_dir, projects_dir


@pytest.mark.asyncio
async def test_copy_session_id(mock_sessions: tuple[Path, Path]) -> None:
    sessions_dir, projects_dir = mock_sessions

    app = CctopApp(recent=timedelta(0))
    app._manager._sessions_dir = sessions_dir
    app._manager._projects_dir = projects_dir

    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        # Press 'c' to copy session ID
        await pilot.press("c")
        await pilot.pause()
        # Verify the clipboard contains the session ID
        assert app.clipboard == "test-session-abc"
        await pilot.press("q")
