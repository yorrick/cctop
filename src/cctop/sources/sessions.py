import json
import os
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from pydantic import BaseModel


class RawSession(BaseModel):
    """Raw session data from ~/.claude/sessions/{pid}.json."""

    pid: int
    session_id: str
    cwd: Path
    started_at: datetime

    @property
    def is_alive(self) -> bool:
        return is_pid_alive(self.pid)


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def discover_sessions(sessions_dir: Path) -> list[RawSession]:
    """Read all session files from ~/.claude/sessions/ and return parsed sessions."""
    if not sessions_dir.is_dir():
        return []

    sessions: list[RawSession] = []
    for path in sessions_dir.glob("*.json"):
        try:
            first_line = path.read_text().split("\n", 1)[0]
            data = json.loads(first_line)
            sessions.append(
                RawSession(
                    pid=data["pid"],
                    session_id=data["sessionId"],
                    cwd=Path(data["cwd"]),
                    started_at=datetime.fromtimestamp(data["startedAt"] / 1000, tz=timezone.utc),
                )
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Skipping invalid session file {}: {}", path.name, e)

    return sessions
