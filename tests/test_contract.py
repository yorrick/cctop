"""Contract tests that run real Claude Code sessions.

These tests verify that Claude Code produces the file/event artifacts
cctop depends on, and that SessionManager correctly ingests them.

Run with: pytest -m contract
Requires: claude CLI installed, costs API tokens.

Key contract findings documented by these tests:
- --print sessions do NOT create PID files (only interactive sessions do)
- Hook events and transcripts DO work for --print sessions
- Claude Code replaces both / and _ with - in project directory encoding
- session_end fires on /clear AND on process exit (not just exit)
- --resume reuses the original session ID in hooks and appends to transcript
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import TypeVar

import pytest

from cctop.models import Event
from cctop.sources.index import encode_cwd
from cctop.sources.merger import SessionManager
from cctop.sources.sessions import is_pid_alive

T = TypeVar("T")

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

SHORT_SESSION_TIMEOUT = 60
LONG_SESSION_TIMEOUT = 120
POLL_TIMEOUT = 30.0
POLL_INTERVAL = 0.5

LONG_RUNNING_PROMPT = "Write a bash script that prints hello every 2 seconds for 30 seconds. Run it."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def wait_for(
    predicate: Callable[[], T],
    *,
    timeout: float = POLL_TIMEOUT,
    interval: float = POLL_INTERVAL,
    desc: str = "",
) -> T:
    """Poll predicate until it returns a truthy value or timeout expires."""
    deadline = time.monotonic() + timeout
    last_result = None
    while time.monotonic() < deadline:
        last_result = predicate()
        if last_result:
            return last_result
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for: {desc or 'condition'} (last result: {last_result})")


def read_events(events_dir: Path, *, session_id: str | None = None) -> list[dict]:  # type: ignore[type-arg]
    """Read events from the isolated events.jsonl, optionally filtering by session ID."""
    events_file = events_dir / "events.jsonl"
    if not events_file.is_file():
        return []
    events: list[dict] = []  # type: ignore[type-arg]
    for line in events_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if session_id is None or data.get("sid") == session_id:
                events.append(data)
        except json.JSONDecodeError:
            continue
    return events


def read_events_typed(events_dir: Path, *, session_id: str | None = None) -> list[Event]:
    """Read events as typed Event objects."""
    return [Event.model_validate(e) for e in read_events(events_dir, session_id=session_id)]


def snapshot_pid_files() -> set[str]:
    """Return the set of PID file names currently in ~/.claude/sessions/."""
    if not CLAUDE_SESSIONS_DIR.is_dir():
        return set()
    return {p.name for p in CLAUDE_SESSIONS_DIR.glob("*.json")}


def transcript_path(work_dir: Path, session_id: str) -> Path:
    """Return the expected transcript path for a session."""
    encoded = encode_cwd(work_dir)
    return CLAUDE_PROJECTS_DIR / encoded / f"{session_id}.jsonl"


def read_transcript_messages(work_dir: Path, session_id: str) -> list[dict]:  # type: ignore[type-arg]
    """Read transcript and return user/assistant messages."""
    path = transcript_path(work_dir, session_id)
    if not path.is_file():
        return []
    messages: list[dict] = []  # type: ignore[type-arg]
    for line in path.read_text().splitlines():
        try:
            data = json.loads(line)
            if data.get("type") in ("user", "assistant"):
                messages.append(data)
        except json.JSONDecodeError:
            continue
    return messages


def _write_session_file(sessions_dir: Path, pid: int, session_id: str, cwd: str) -> None:
    """Write a synthetic PID file for testing SessionManager integration."""
    data = {"pid": pid, "sessionId": session_id, "cwd": cwd, "startedAt": int(time.time() * 1000)}
    (sessions_dir / f"{pid}.json").write_text(json.dumps(data))


def run_claude_print(
    work_dir: Path,
    session_id: str,
    prompt: str,
    events_dir: Path,
    *,
    resume: bool = False,
    timeout: int = SHORT_SESSION_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a claude --print session synchronously."""
    cmd = ["claude", "--print", "--model", "haiku"]
    if resume:
        cmd += ["--resume", session_id]
    else:
        cmd += ["--session-id", session_id]
    cmd.append(prompt)

    env = os.environ.copy()
    env["CCTOP_DATA_DIR"] = str(events_dir)

    return subprocess.run(
        cmd,
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


@contextmanager
def background_claude(
    work_dir: Path,
    session_id: str,
    prompt: str,
    events_dir: Path,
) -> Generator[subprocess.Popen[str]]:
    """Start claude --print in background with --dangerously-skip-permissions.

    Yields Popen, sends SIGTERM on exit.
    """
    cmd = [
        "claude",
        "--print",
        "--model",
        "haiku",
        "--session-id",
        session_id,
        "--dangerously-skip-permissions",
        prompt,
    ]
    env = os.environ.copy()
    env["CCTOP_DATA_DIR"] = str(events_dir)

    proc = subprocess.Popen(
        cmd,
        cwd=work_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def cleanup_transcript(work_dir: Path, session_id: str) -> None:
    """Remove transcript file and empty project directory."""
    path = transcript_path(work_dir, session_id)
    if path.is_file():
        path.unlink()
    # Remove parent dir if empty
    if path.parent.is_dir() and not any(path.parent.iterdir()):
        path.parent.rmdir()


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_basic_lifecycle(tmp_path: Path) -> None:
    """A simple --print session produces expected events, transcript, and PID lifecycle."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        result = run_claude_print(work_dir, session_id, "respond with just the word PONG", events_dir)
        assert result.returncode == 0, f"claude --print failed: {result.stderr}"

        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]

        assert "session_start" in event_types, f"No session_start event. Events: {event_types}"
        assert "stop" in event_types, f"No stop event. Events: {event_types}"
        assert "session_end" in event_types, f"No session_end event. Events: {event_types}"

        start_idx = event_types.index("session_start")
        stop_idx = event_types.index("stop")
        end_idx = event_types.index("session_end")
        assert start_idx < stop_idx < end_idx, f"Wrong event order: {event_types}"

        start_event = events[start_idx]
        assert start_event["cwd"] == str(work_dir), f"session_start cwd mismatch: {start_event['cwd']} != {work_dir}"

        tpath = transcript_path(work_dir, session_id)
        assert tpath.is_file(), f"Transcript not found at {tpath}"

        messages = read_transcript_messages(work_dir, session_id)
        user_msgs = [m for m in messages if m["type"] == "user"]
        asst_msgs = [m for m in messages if m["type"] == "assistant"]
        assert len(user_msgs) >= 1, f"Expected at least 1 user message, got {len(user_msgs)}"
        assert len(asst_msgs) >= 1, f"Expected at least 1 assistant message, got {len(asst_msgs)}"
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_session_resumption(tmp_path: Path) -> None:
    """--resume reuses the same session ID and appends to the same transcript."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        result1 = run_claude_print(work_dir, session_id, "respond with just the word PONG", events_dir)
        assert result1.returncode == 0, f"First session failed: {result1.stderr}"
        time.sleep(2)

        result2 = run_claude_print(work_dir, session_id, "respond with just the word PING", events_dir, resume=True)
        assert result2.returncode == 0, f"Resume session failed: {result2.stderr}"

        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]

        assert event_types.count("session_start") == 2, (
            f"Expected 2 session_start events, got {event_types.count('session_start')}: {event_types}"
        )
        assert event_types.count("session_end") == 2, (
            f"Expected 2 session_end events, got {event_types.count('session_end')}: {event_types}"
        )

        tpath = transcript_path(work_dir, session_id)
        assert tpath.is_file(), f"Transcript not found at {tpath}"

        messages = read_transcript_messages(work_dir, session_id)
        user_msgs = [m for m in messages if m["type"] == "user"]
        asst_msgs = [m for m in messages if m["type"] == "assistant"]
        assert len(user_msgs) >= 2, f"Expected at least 2 user messages, got {len(user_msgs)}"
        assert len(asst_msgs) >= 2, f"Expected at least 2 assistant messages, got {len(asst_msgs)}"
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_long_lived_session_events(tmp_path: Path) -> None:
    """A long-running --print session produces tool_start/tool_end events while active."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir):
            # Wait for session_start
            wait_for(
                lambda: any(e["type"] == "session_start" for e in read_events(events_dir, session_id=session_id)),
                desc="session_start event",
            )

            # Wait for tool_start (Bash tool for running the script)
            wait_for(
                lambda: any(e["type"] == "tool_start" for e in read_events(events_dir, session_id=session_id)),
                desc="tool_start event",
            )

            # Verify tool events are present
            events = read_events(events_dir, session_id=session_id)
            tool_events = [e for e in events if e["type"] in ("tool_start", "tool_end")]
            assert len(tool_events) >= 1, f"Expected tool events, got: {[e['type'] for e in events]}"

            # Transcript should be growing
            tpath = transcript_path(work_dir, session_id)
            assert tpath.is_file(), f"Transcript not found at {tpath}"

        # After exit, session_end should appear
        time.sleep(2)
        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]
        assert "session_end" in event_types, f"No session_end after exit. Events: {event_types}"
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_print_sessions_do_not_create_pid_files(tmp_path: Path) -> None:
    """--print sessions do NOT create PID files (only interactive sessions do).

    This documents a key contract: cctop cannot discover --print sessions
    via PID files. It must rely on hook events instead.
    """
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    pid_snapshot = snapshot_pid_files()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir):
            # Wait for session to be fully active
            wait_for(
                lambda: any(e["type"] == "tool_start" for e in read_events(events_dir, session_id=session_id)),
                desc="tool_start event",
            )
            # Give extra time for PID file to appear (if it would)
            time.sleep(3)

            # No new PID file should have appeared
            current = snapshot_pid_files()
            new_files = current - pid_snapshot
            assert len(new_files) == 0, (
                f"--print session created PID file(s): {new_files}. "
                f"Contract violation: --print sessions should not create PID files."
            )
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_session_end_does_not_mean_process_dead(tmp_path: Path) -> None:
    """A session_end event while the PID is alive must NOT mark the session offline.

    Uses a hybrid approach: real Claude Code events for the session lifecycle,
    combined with a synthetic PID file to test SessionManager's handling of
    session_end when a PID is still alive. This simulates what happens when a
    user runs /clear in an interactive session.
    """
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    # Synthetic sessions/projects dirs for isolated SessionManager
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir) as proc:
            # Wait for real events
            wait_for(
                lambda: any(e["type"] == "tool_start" for e in read_events(events_dir, session_id=session_id)),
                desc="tool_start event",
            )

            # Create a synthetic PID file using the real process's PID
            # (simulates an interactive session that WOULD have a PID file)
            pid_sid = "synthetic-" + session_id[:8]
            _write_session_file(sessions_dir, proc.pid, pid_sid, str(work_dir))
            assert is_pid_alive(proc.pid), "Background process should be alive"

            # Build SessionManager with synthetic sessions dir
            mgr = SessionManager(
                sessions_dir=sessions_dir,
                projects_dir=projects_dir,
                recent=timedelta(hours=1),
            )
            mgr.refresh()

            # Verify session is discovered and alive
            assert len(mgr.sessions) == 1
            assert mgr.sessions[0].status == "idle"
            assert mgr.sessions[0].session_id == pid_sid

            # Apply a session_end event for this session
            session_end_event = Event(
                ts=int(time.time() * 1000),
                sid=pid_sid,
                type="session_end",
            )
            mgr.apply_events([session_end_event])

            # THE KEY ASSERTION: session must NOT be offline because PID is alive
            assert mgr.sessions[0].status != "offline", (
                f"Session is offline despite PID {proc.pid} being alive! session_end should not kill a live session."
            )
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_session_id_in_events_and_transcript(tmp_path: Path) -> None:
    """Hook events and transcript both use the --session-id we specified."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir):
            wait_for(
                lambda: any(e["type"] == "tool_start" for e in read_events(events_dir, session_id=session_id)),
                desc="tool_start event",
            )

            # Hook events use our --session-id
            events = read_events(events_dir, session_id=session_id)
            assert len(events) > 0, "No events for our session_id"

            # session_start event has our session_id
            start_events = [e for e in events if e["type"] == "session_start"]
            assert len(start_events) >= 1, "No session_start with our session_id"
            assert start_events[0]["sid"] == session_id

            # Transcript is named after our --session-id
            tpath = transcript_path(work_dir, session_id)
            assert tpath.is_file(), f"Transcript not at expected path {tpath}"

            # Transcript has actual messages
            messages = read_transcript_messages(work_dir, session_id)
            assert len(messages) >= 1, f"Transcript has no messages: {tpath}"
    finally:
        cleanup_transcript(work_dir, session_id)
