import json
import time
from pathlib import Path

from cctop.sources.events import MAX_EVENTS_FILE_SIZE, EventsTailer


def _write_event(f, ts: int, sid: str = "abc") -> None:
    f.write(json.dumps({"ts": ts, "sid": sid, "type": "stop"}) + "\n")


def test_cleanup_skips_small_file(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(json.dumps({"ts": 1000, "sid": "abc", "type": "stop"}) + "\n")

    tailer = EventsTailer(events_file)
    tailer.cleanup_if_needed()

    # File should be untouched
    assert events_file.read_text().strip() != ""


def test_cleanup_removes_old_events(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"

    now_ms = int(time.time() * 1000)
    old_ts = now_ms - (25 * 3600 * 1000)  # 25 hours ago
    recent_ts = now_ms - (1 * 3600 * 1000)  # 1 hour ago

    # Write enough data to exceed 10 MB
    with events_file.open("w") as f:
        # Write old events to bulk up the file
        line = json.dumps({"ts": old_ts, "sid": "old", "type": "stop", "padding": "x" * 500}) + "\n"
        lines_needed = (MAX_EVENTS_FILE_SIZE // len(line)) + 100
        for _ in range(lines_needed):
            f.write(line)
        # Write one recent event
        f.write(json.dumps({"ts": recent_ts, "sid": "recent", "type": "stop"}) + "\n")

    assert events_file.stat().st_size > MAX_EVENTS_FILE_SIZE

    tailer = EventsTailer(events_file)
    tailer.cleanup_if_needed()

    # Should only keep the recent event
    remaining = events_file.read_text().strip().split("\n")
    assert len(remaining) == 1
    assert json.loads(remaining[0])["sid"] == "recent"


def test_cleanup_resets_offset(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(json.dumps({"ts": 1000, "sid": "abc", "type": "stop"}) + "\n")

    tailer = EventsTailer(events_file)
    tailer.read_new()  # Advances offset
    assert tailer._offset > 0

    # Force cleanup by writing a huge file
    now_ms = int(time.time() * 1000)
    with events_file.open("w") as f:
        line = (
            json.dumps({"ts": now_ms - (25 * 3600 * 1000), "sid": "old", "type": "stop", "padding": "x" * 500}) + "\n"
        )
        for _ in range((MAX_EVENTS_FILE_SIZE // len(line)) + 100):
            f.write(line)

    tailer.cleanup_if_needed()
    assert tailer._offset == 0


def test_hooks_installed_false(tmp_path: Path) -> None:
    tailer = EventsTailer(tmp_path / "nonexistent" / "events.jsonl")
    assert tailer.hooks_installed is False


def test_hooks_installed_true(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    tailer = EventsTailer(data_dir / "events.jsonl")
    assert tailer.hooks_installed is True
