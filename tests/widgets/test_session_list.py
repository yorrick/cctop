# tests/widgets/test_session_list.py
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.binding import Binding

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
