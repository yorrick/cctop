import json
import re
from datetime import datetime
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
    name: str | None = None

    model_config = {"populate_by_name": True}


def encode_cwd(cwd: Path) -> str:
    """Encode a cwd path to the format used by Claude Code for project directories.

    /Users/foo/work -> -Users-foo-work
    /tmp/my_project -> -tmp-my-project

    Claude Code replaces both / and _ with - in project directory names.
    """
    return str(cwd).replace("/", "-").replace("_", "-")


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

    # Fallback: read the transcript JSONL by exact session ID
    transcript_path = project_dir / f"{session_id}.jsonl"
    if transcript_path.is_file():
        return _read_transcript_metadata(session_id, transcript_path)

    return None


# System tags injected by Claude Code into user messages — not actual user content
_SYSTEM_TAGS = (
    "local-command-caveat",
    "system-reminder",
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "bash-input",
    "bash-stdout",
    "bash-stderr",
    "task-notification",
)
_TAG_GROUP = "|".join(_SYSTEM_TAGS)
_SYSTEM_TAG_RE = re.compile(
    rf"<(?:{_TAG_GROUP})[^>]*>.*?</(?:{_TAG_GROUP})>",
    re.DOTALL,
)


def _extract_user_text(data: dict) -> str | None:  # type: ignore[type-arg]
    """Extract clean user text from a transcript user message, stripping system tags."""
    content = data.get("message", {}).get("content", "")
    if isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                text = block["text"]
                # Strip system tags
                text = _SYSTEM_TAG_RE.sub("", text).strip()
                if text:
                    return text
    elif isinstance(content, str):
        text = _SYSTEM_TAG_RE.sub("", content).strip()
        if text:
            return text
    return None


def _read_transcript_metadata(session_id: str, transcript_path: Path) -> IndexEntry | None:
    """Extract metadata from a session transcript JSONL file."""
    first_prompt: str | None = None
    message_count = 0
    git_branch: str | None = None
    summary: str | None = None
    name: str | None = None

    try:
        with transcript_path.open() as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "custom-title":
                    name = data.get("customTitle")

                elif msg_type == "user":
                    message_count += 1
                    if first_prompt is None:
                        text = _extract_user_text(data)
                        if text:
                            first_prompt = text[:200]

                elif msg_type == "assistant":
                    message_count += 1

                elif msg_type == "summary":
                    # Some transcripts include a summary entry
                    summary = data.get("summary", data.get("text"))

    except OSError as e:
        logger.warning("Failed to read transcript {}: {}", transcript_path, e)
        return None

    if first_prompt is None and message_count == 0 and name is None:
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
            "name": name,
        }
    )


def find_transcript_path(
    projects_dir: Path,
    cwd: Path,
    session_id: str,
    started_at: datetime,
) -> Path | None:
    """Find the .jsonl transcript path for a session.

    Step 1: direct match by session_id.
    Step 2: scan for most-recently-modified .jsonl after started_at (handles
            resumed sessions where PID-file ID differs from transcript ID).
    """
    encoded = encode_cwd(cwd)
    project_dir = projects_dir / encoded

    # Step 1: direct match
    direct = project_dir / f"{session_id}.jsonl"
    if direct.is_file():
        return direct

    if not project_dir.is_dir():
        return None

    # Step 2: find most-recently-modified .jsonl modified after session started
    started_ts = started_at.timestamp()
    candidates: list[Path] = []
    for t in project_dir.glob("*.jsonl"):
        if t.stem != session_id and t.stat().st_mtime >= started_ts - 300:
            candidates.append(t)

    if not candidates:
        return None

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]
