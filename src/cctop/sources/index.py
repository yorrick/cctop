import json
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field


class IndexEntry(BaseModel):
    """A single entry from sessions-index.json."""

    session_id: str = Field(alias="sessionId")
    summary: str | None = None
    first_prompt: str | None = Field(default=None, alias="firstPrompt")
    git_branch: str | None = Field(default=None, alias="gitBranch")
    message_count: int = Field(default=0, alias="messageCount")

    model_config = {"populate_by_name": True}


def encode_cwd(cwd: Path) -> str:
    """Encode a cwd path to the format used by Claude Code for project directories.

    /Users/foo/work -> -Users-foo-work
    """
    return str(cwd).replace("/", "-")


def find_index_entry(projects_dir: Path, cwd: Path, session_id: str) -> IndexEntry | None:
    """Look up a session's metadata in the sessions-index.json for its project directory."""
    encoded = encode_cwd(cwd)
    index_path = projects_dir / encoded / "sessions-index.json"

    if not index_path.is_file():
        return None

    try:
        data = json.loads(index_path.read_text())
        for entry_data in data.get("entries", []):
            if entry_data.get("sessionId") == session_id:
                return IndexEntry.model_validate(entry_data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to read sessions-index.json at {}: {}", index_path, e)

    return None
