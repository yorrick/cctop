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
