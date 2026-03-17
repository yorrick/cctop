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
    """Look up a session's metadata from sessions-index.json or transcript fallback.

    The sessions-index.json is a lazy cache — active sessions may not be listed.
    For those, we fall back to reading the transcript JSONL to extract the first
    user prompt and count messages.
    """
    encoded = encode_cwd(cwd)
    project_dir = projects_dir / encoded

    # Try the index first
    index_path = project_dir / "sessions-index.json"
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text())
            for entry_data in data.get("entries", []):
                if entry_data.get("sessionId") == session_id:
                    return IndexEntry.model_validate(entry_data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to read sessions-index.json at {}: {}", index_path, e)

    # Fallback: read the transcript JSONL directly
    transcript_path = project_dir / f"{session_id}.jsonl"
    if transcript_path.is_file():
        return _read_transcript_metadata(session_id, transcript_path)

    return None


def _read_transcript_metadata(session_id: str, transcript_path: Path) -> IndexEntry | None:
    """Extract metadata from a session transcript JSONL file."""
    first_prompt: str | None = None
    message_count = 0
    git_branch: str | None = None
    summary: str | None = None

    try:
        with transcript_path.open() as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "user":
                    message_count += 1
                    if first_prompt is None:
                        content = data.get("message", {}).get("content", "")
                        if isinstance(content, list):
                            for block in content:
                                if block.get("type") == "text":
                                    first_prompt = block["text"][:200]
                                    break
                        elif isinstance(content, str):
                            first_prompt = content[:200]

                elif msg_type == "assistant":
                    message_count += 1

                elif msg_type == "summary":
                    # Some transcripts include a summary entry
                    summary = data.get("summary", data.get("text"))

    except OSError as e:
        logger.warning("Failed to read transcript {}: {}", transcript_path, e)
        return None

    if first_prompt is None and message_count == 0:
        return None

    # Use first prompt as summary if no real summary exists
    if summary is None and first_prompt:
        summary = first_prompt[:120] + ("..." if len(first_prompt) > 120 else "")

    return IndexEntry.model_validate(
        {
            "sessionId": session_id,
            "summary": summary,
            "firstPrompt": first_prompt,
            "gitBranch": git_branch,
            "messageCount": message_count,
        }
    )
