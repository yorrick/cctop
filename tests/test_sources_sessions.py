import json
import os
from pathlib import Path

from cctop.sources.sessions import discover_sessions, is_pid_alive


def test_discover_sessions_reads_json_files(tmp_path: Path) -> None:
    session_data = {"pid": os.getpid(), "sessionId": "abc-123", "cwd": "/tmp/test", "startedAt": 1000}
    (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(session_data))

    result = discover_sessions(tmp_path)
    assert len(result) == 1
    assert result[0].session_id == "abc-123"
    assert result[0].pid == os.getpid()
    assert result[0].cwd == Path("/tmp/test")


def test_discover_sessions_skips_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "99999.json").write_text("not json")
    result = discover_sessions(tmp_path)
    assert len(result) == 0


def test_discover_sessions_empty_dir(tmp_path: Path) -> None:
    result = discover_sessions(tmp_path)
    assert len(result) == 0


def test_discover_sessions_nonexistent_dir(tmp_path: Path) -> None:
    result = discover_sessions(tmp_path / "nonexistent")
    assert len(result) == 0


def test_is_pid_alive_current_process() -> None:
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_dead_process() -> None:
    assert is_pid_alive(99999999) is False
