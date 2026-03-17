import json
from pathlib import Path

from cctop.sources.events import EventsTailer


def test_tailer_reads_new_events(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text("")

    tailer = EventsTailer(events_file)

    with events_file.open("a") as f:
        f.write(json.dumps({"ts": 1000, "sid": "abc", "type": "tool_start", "tool": "Bash", "cwd": "/tmp"}) + "\n")
        f.write(json.dumps({"ts": 1001, "sid": "abc", "type": "stop"}) + "\n")

    events = tailer.read_new()
    assert len(events) == 2
    assert events[0].type == "tool_start"
    assert events[0].tool == "Bash"
    assert events[1].type == "stop"


def test_tailer_tracks_offset(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(json.dumps({"ts": 1000, "sid": "abc", "type": "stop"}) + "\n")

    tailer = EventsTailer(events_file)
    events = tailer.read_new()
    assert len(events) == 1

    events = tailer.read_new()
    assert len(events) == 0

    with events_file.open("a") as f:
        f.write(json.dumps({"ts": 2000, "sid": "abc", "type": "tool_start", "tool": "Read", "cwd": "/tmp"}) + "\n")

    events = tailer.read_new()
    assert len(events) == 1
    assert events[0].tool == "Read"


def test_tailer_skips_malformed_lines(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        "not json\n"
        + json.dumps({"ts": 1000, "sid": "abc", "type": "stop"})
        + "\n"
        + '{"ts": 2000, "sid": "abc", "type": "bad_type"}\n'
    )

    tailer = EventsTailer(events_file)
    events = tailer.read_new()
    assert len(events) == 1
    assert events[0].type == "stop"


def test_tailer_nonexistent_file(tmp_path: Path) -> None:
    tailer = EventsTailer(tmp_path / "nonexistent.jsonl")
    events = tailer.read_new()
    assert len(events) == 0
