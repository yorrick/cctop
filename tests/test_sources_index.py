import json
from pathlib import Path

from cctop.sources.index import encode_cwd, find_index_entry


def test_encode_cwd() -> None:
    assert encode_cwd(Path("/Users/foo/work")) == "-Users-foo-work"


def test_encode_cwd_trailing_slash() -> None:
    assert encode_cwd(Path("/Users/foo/work/")) == "-Users-foo-work"


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
