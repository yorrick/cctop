import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from cctop.app import CctopApp


@pytest.fixture
def mock_sessions(tmp_path: Path) -> tuple[Path, Path]:
    """Create mock Claude session files."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Create a session file with current PID (so it appears alive)
    data = {"pid": os.getpid(), "sessionId": "test-session-1", "cwd": str(tmp_path), "startedAt": 1773764468081}
    (sessions_dir / f"{os.getpid()}.json").write_text(json.dumps(data))

    return sessions_dir, projects_dir


@pytest.mark.asyncio
async def test_app_launches_and_quits(mock_sessions: tuple[Path, Path]) -> None:
    sessions_dir, projects_dir = mock_sessions

    app = CctopApp(recent=timedelta(0))
    app._manager._sessions_dir = sessions_dir
    app._manager._projects_dir = projects_dir

    async with app.run_test() as pilot:
        # App should have mounted
        assert app.is_running
        # Quit
        await pilot.press("q")


@pytest.mark.asyncio
async def test_app_shows_sessions(mock_sessions: tuple[Path, Path]) -> None:
    sessions_dir, projects_dir = mock_sessions

    app = CctopApp(recent=timedelta(0))
    app._manager._sessions_dir = sessions_dir
    app._manager._projects_dir = projects_dir

    async with app.run_test(size=(120, 30)) as pilot:
        # Wait for first poll
        await pilot.pause()
        # Check that the app rendered something
        assert len(app._manager.sessions) == 1
        await pilot.press("q")
