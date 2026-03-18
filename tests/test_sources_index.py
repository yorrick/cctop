import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from cctop.sources.index import (
    _read_transcript_metadata,
    encode_cwd,
    find_index_entry,
    find_transcript_path,
)


def test_encode_cwd() -> None:
    assert encode_cwd(Path("/Users/foo/work")) == "-Users-foo-work"


def test_encode_cwd_trailing_slash() -> None:
    assert encode_cwd(Path("/Users/foo/work/")) == "-Users-foo-work"


def test_encode_cwd_dotfile_directory() -> None:
    """Dotfile directories like .worktrees should have the dot replaced with -."""
    assert encode_cwd(Path("/Users/foo/work/cctop/.worktrees/backlog")) == "-Users-foo-work-cctop--worktrees-backlog"


def test_find_index_entry_found(tmp_path: Path) -> None:
    projects_dir = tmp_path / "-tmp-test"
    projects_dir.mkdir()
    index_data = {
        "version": 1,
        "originalPath": "/tmp/test",
        "entries": [
            {
                "sessionId": "abc-123",
                "summary": "Test summary",
                "firstPrompt": "do something",
                "gitBranch": "main",
                "messageCount": 5,
                "created": "2026-01-01T00:00:00.000Z",
                "modified": "2026-01-01T01:00:00.000Z",
                "projectPath": "/tmp/test",
                "isSidechain": False,
            }
        ],
    }
    (projects_dir / "sessions-index.json").write_text(json.dumps(index_data))

    entry = find_index_entry(tmp_path, Path("/tmp/test"), "abc-123")
    assert entry is not None
    assert entry.summary == "Test summary"
    assert entry.git_branch == "main"
    assert entry.message_count == 5


def test_find_index_entry_not_found(tmp_path: Path) -> None:
    projects_dir = tmp_path / "-tmp-test"
    projects_dir.mkdir()
    index_data = {"version": 1, "originalPath": "/tmp/test", "entries": []}
    (projects_dir / "sessions-index.json").write_text(json.dumps(index_data))

    entry = find_index_entry(tmp_path, Path("/tmp/test"), "nonexistent")
    assert entry is None


def test_find_index_entry_no_index_file(tmp_path: Path) -> None:
    entry = find_index_entry(tmp_path, Path("/tmp/test"), "abc-123")
    assert entry is None


def test_find_transcript_path_direct_match(tmp_path: Path) -> None:
    """Direct match: <session_id>.jsonl exists."""
    projects_dir = tmp_path
    cwd = Path("/tmp/myproject")
    session_id = "abc-123"
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    project_dir = tmp_path / "-tmp-myproject"
    project_dir.mkdir()
    transcript = project_dir / f"{session_id}.jsonl"
    transcript.write_text('{"type":"user"}\n')

    result = find_transcript_path(projects_dir, cwd, session_id, started_at)
    assert result == transcript


def test_find_transcript_path_fallback_active(tmp_path: Path) -> None:
    """Fallback: no direct match, finds most-recently-modified .jsonl."""
    projects_dir = tmp_path
    cwd = Path("/tmp/myproject")
    session_id = "pid-session-id"
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    project_dir = tmp_path / "-tmp-myproject"
    project_dir.mkdir()

    # A different transcript (the actual transcript for a resumed session)
    other = project_dir / "transcript-abc.jsonl"
    other.write_text('{"type":"user"}\n')
    # Set mtime to after started_at
    os.utime(other, (time.time(), started_at.timestamp() + 60))

    result = find_transcript_path(projects_dir, cwd, session_id, started_at)
    assert result == other


def test_find_transcript_path_no_match(tmp_path: Path) -> None:
    """Returns None when no transcript found."""
    projects_dir = tmp_path
    cwd = Path("/tmp/myproject")
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = find_transcript_path(projects_dir, cwd, "nonexistent", started_at)
    assert result is None


def test_read_transcript_extracts_custom_title(tmp_path: Path) -> None:
    """customTitle in first line is extracted into IndexEntry.name."""
    transcript = tmp_path / "abc-123.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "my-feature", "sessionId": "abc-123"})
        + "\n"
        + json.dumps({"type": "user", "message": {"content": "hello"}})
        + "\n"
    )
    entry = _read_transcript_metadata("abc-123", transcript)
    assert entry is not None
    assert entry.name == "my-feature"


def test_read_transcript_name_set_even_with_no_messages(tmp_path: Path) -> None:
    """Returns IndexEntry with name even when message_count == 0."""
    transcript = tmp_path / "abc-123.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "early-session", "sessionId": "abc-123"}) + "\n"
    )
    entry = _read_transcript_metadata("abc-123", transcript)
    assert entry is not None
    assert entry.name == "early-session"
    assert entry.message_count == 0


def test_read_transcript_name_none_when_no_custom_title(tmp_path: Path) -> None:
    """Returns IndexEntry with name=None when transcript has no custom-title."""
    transcript = tmp_path / "abc-123.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n")
    entry = _read_transcript_metadata("abc-123", transcript)
    assert entry is not None
    assert entry.name is None
