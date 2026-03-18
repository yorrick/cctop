from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cctop.sources.iterm2 import ITermBridge


@pytest.fixture(autouse=True)
def _reset_iterm2_globals() -> None:
    """Reset lazy-loaded module globals between tests."""
    import cctop.sources.iterm2 as mod

    mod._iterm2 = None
    mod._psutil = None


@pytest.mark.asyncio
async def test_connect_success() -> None:
    mock_connection = AsyncMock()
    mock_iterm2 = MagicMock()
    mock_iterm2.Connection.async_create = AsyncMock(return_value=mock_connection)

    bridge = ITermBridge()
    with patch.dict("sys.modules", {"iterm2": mock_iterm2, "psutil": MagicMock()}):
        await bridge.connect()

    assert bridge.available is True


@pytest.mark.asyncio
async def test_connect_import_error() -> None:
    bridge = ITermBridge()
    with patch.dict("sys.modules", {"iterm2": None, "psutil": None}):
        await bridge.connect()

    assert bridge.available is False


@pytest.mark.asyncio
async def test_connect_api_server_disabled() -> None:
    mock_iterm2 = MagicMock()
    mock_iterm2.Connection.async_create = AsyncMock(side_effect=ConnectionRefusedError("API server disabled"))

    bridge = ITermBridge()
    with patch.dict("sys.modules", {"iterm2": mock_iterm2, "psutil": MagicMock()}):
        await bridge.connect()

    assert bridge.available is False


@pytest.mark.asyncio
async def test_activate_session_success() -> None:
    """PID walk-up finds matching iTerm2 session and activates it."""
    mock_iterm_session = AsyncMock()
    mock_iterm_session.session_id = "iterm-session-1"

    # Mock psutil process chain: claude(100) -> fish(50) -> login(10)
    mock_login = MagicMock()
    mock_login.pid = 10
    mock_login.parent.return_value = None

    mock_fish = MagicMock()
    mock_fish.pid = 50
    mock_fish.parent.return_value = mock_login

    mock_claude = MagicMock()
    mock_claude.pid = 100
    mock_claude.parent.return_value = mock_fish

    # Mock iTerm2 app with one session whose root PID is 10
    mock_app = AsyncMock()
    mock_tab = MagicMock()
    mock_tab.sessions = [mock_iterm_session]
    mock_window = MagicMock()
    mock_window.tabs = [mock_tab]
    mock_app.windows = [mock_window]
    mock_iterm_session.async_get_variable = AsyncMock(return_value=10)

    bridge = ITermBridge()
    bridge._available = True
    bridge._connection = MagicMock()

    mock_iterm2_mod = MagicMock()
    mock_iterm2_mod.async_get_app = AsyncMock(return_value=mock_app)
    mock_psutil_mod = MagicMock()
    mock_psutil_mod.Process.return_value = mock_claude

    with (
        patch("cctop.sources.iterm2._iterm2", mock_iterm2_mod),
        patch("cctop.sources.iterm2._psutil", mock_psutil_mod),
    ):
        result = await bridge.activate_session(100)

    assert result is True
    mock_iterm_session.async_activate.assert_awaited_once()


@pytest.mark.asyncio
async def test_activate_session_no_match() -> None:
    """PID walk-up finds no matching iTerm2 session."""
    mock_app = AsyncMock()
    mock_app.windows = []  # No windows/sessions

    mock_process = MagicMock()
    mock_process.pid = 100
    mock_process.parent.return_value = MagicMock(pid=1, parent=MagicMock(return_value=None))

    bridge = ITermBridge()
    bridge._available = True
    bridge._connection = MagicMock()

    mock_iterm2_mod = MagicMock()
    mock_iterm2_mod.async_get_app = AsyncMock(return_value=mock_app)
    mock_psutil_mod = MagicMock()
    mock_psutil_mod.Process.return_value = mock_process

    with (
        patch("cctop.sources.iterm2._iterm2", mock_iterm2_mod),
        patch("cctop.sources.iterm2._psutil", mock_psutil_mod),
    ):
        result = await bridge.activate_session(100)

    assert result is False


@pytest.mark.asyncio
async def test_activate_session_dead_pid() -> None:
    """Dead PID raises NoSuchProcess, returns False."""
    bridge = ITermBridge()
    bridge._available = True
    bridge._connection = MagicMock()

    mock_iterm2_mod = MagicMock()
    mock_psutil_mod = MagicMock()
    mock_psutil_mod.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    mock_psutil_mod.Process.side_effect = mock_psutil_mod.NoSuchProcess(99999)

    with (
        patch("cctop.sources.iterm2._iterm2", mock_iterm2_mod),
        patch("cctop.sources.iterm2._psutil", mock_psutil_mod),
    ):
        result = await bridge.activate_session(99999)

    assert result is False


@pytest.mark.asyncio
async def test_activate_session_not_available() -> None:
    """When bridge is not available, returns False immediately."""
    bridge = ITermBridge()
    assert bridge.available is False

    result = await bridge.activate_session(12345)
    assert result is False
