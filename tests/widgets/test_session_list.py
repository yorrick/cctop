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
