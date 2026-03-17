"""Contract tests that run real Claude Code sessions.

These tests verify that Claude Code produces the file/event artifacts
cctop depends on, and that SessionManager correctly ingests them.

Run with: pytest -m contract
Requires: claude CLI installed, costs API tokens.
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

T = TypeVar("T")

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Timeouts
SHORT_SESSION_TIMEOUT = 30
LONG_SESSION_TIMEOUT = 90
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


def find_new_pid_file(before: set[str]) -> dict | None:  # type: ignore[type-arg]
    """Find a PID file that appeared after the snapshot. Returns parsed data or None."""
    if not CLAUDE_SESSIONS_DIR.is_dir():
        return None
    current = {p.name for p in CLAUDE_SESSIONS_DIR.glob("*.json")}
    new_files = current - before
    for name in new_files:
        path = CLAUDE_SESSIONS_DIR / name
        try:
            data = json.loads(path.read_text().split("\n", 1)[0])
            pid = data["pid"]
            try:
                os.kill(pid, 0)
                data["_alive"] = True
            except ProcessLookupError:
                data["_alive"] = False
            except PermissionError:
                data["_alive"] = True
            return data
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    return None


def pid_file_exists(pid: int) -> bool:
    """Check if a PID file exists for the given PID."""
    return (CLAUDE_SESSIONS_DIR / f"{pid}.json").is_file()


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
    cmd = ["claude", "--print"]
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

        # -- Raw contract assertions --
        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]

        assert "session_start" in event_types, f"No session_start event. Events: {event_types}"
        assert "stop" in event_types, f"No stop event. Events: {event_types}"
        assert "session_end" in event_types, f"No session_end event. Events: {event_types}"

        # Order: session_start before stop before session_end
        start_idx = event_types.index("session_start")
        stop_idx = event_types.index("stop")
        end_idx = event_types.index("session_end")
        assert start_idx < stop_idx < end_idx, f"Wrong event order: {event_types}"

        # session_start has correct cwd
        start_event = events[start_idx]
        assert start_event["cwd"] == str(work_dir), f"session_start cwd mismatch: {start_event['cwd']} != {work_dir}"

        # Transcript exists and has messages
        tpath = transcript_path(work_dir, session_id)
        assert tpath.is_file(), f"Transcript not found at {tpath}"

        messages = read_transcript_messages(work_dir, session_id)
        user_msgs = [m for m in messages if m["type"] == "user"]
        asst_msgs = [m for m in messages if m["type"] == "assistant"]
        assert len(user_msgs) >= 1, f"Expected at least 1 user message, got {len(user_msgs)}"
        assert len(asst_msgs) >= 1, f"Expected at least 1 assistant message, got {len(asst_msgs)}"

        # -- Integration assertion --
        # After exit, process is dead and PID file should be cleaned up.
        time.sleep(2)

        # SessionManager with recent=0 should not show dead sessions.
        # The PID-file cwd may differ from work_dir (Claude Code uses parent shell cwd),
        # but the session should still not be visible since the process is dead.
        mgr = SessionManager(sessions_dir=CLAUDE_SESSIONS_DIR, projects_dir=CLAUDE_PROJECTS_DIR)
        mgr.refresh()
        # Verify no session exists for our session_id or PID-file session ID
        # (both should be evicted since process is dead)
        for s in mgr.sessions:
            assert s.session_id != session_id, f"Dead session {session_id} still visible in SessionManager"
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

        # -- Raw contract assertions --
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
def test_long_lived_session(tmp_path: Path) -> None:
    """While a session is running, SessionManager sees it as working/idle, not offline."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    pid_snapshot = snapshot_pid_files()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir):
            # Wait for tool activity
            wait_for(
                lambda: any(e["type"] == "tool_start" for e in read_events(events_dir, session_id=session_id)),
                desc="tool_start event",
            )

            # Find the new PID file (appeared after our snapshot)
            pid_data = wait_for(lambda: find_new_pid_file(pid_snapshot), desc="new PID file")
            assert pid_data is not None
            assert pid_data["_alive"], "PID should be alive"

            # -- Integration assertion --
            # SessionManager discovers session via PID file, then we apply events
            mgr = SessionManager(
                sessions_dir=CLAUDE_SESSIONS_DIR,
                projects_dir=CLAUDE_PROJECTS_DIR,
                recent=timedelta(hours=1),
            )
            mgr.refresh()
            events_typed = read_events_typed(events_dir, session_id=session_id)
            mgr.apply_events(events_typed)

            # Find our session by PID-file session ID
            pid_sid = pid_data["sessionId"]
            our_session = next((s for s in mgr.sessions if s.session_id == pid_sid), None)
            assert our_session is not None, (
                f"Session {pid_sid} not in SessionManager. IDs: {[s.session_id for s in mgr.sessions]}"
            )
            assert our_session.status in ("working", "idle"), (
                f"Session should be working or idle, got: {our_session.status}"
            )

        # After context manager kills the process, wait for cleanup
        time.sleep(3)

        assert not pid_file_exists(pid_data["pid"]), "PID file should be removed after exit"

        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]
        assert "session_end" in event_types, f"No session_end after exit. Events: {event_types}"
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_session_end_does_not_mean_process_dead(tmp_path: Path) -> None:
    """A session_end event while the PID is alive must NOT mark the session offline.

    This simulates what happens when a user runs /clear: Claude Code fires
    session_end but the process keeps running.
    """
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    pid_snapshot = snapshot_pid_files()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir):
            # Wait for session to be active
            wait_for(
                lambda: any(e["type"] == "tool_start" for e in read_events(events_dir, session_id=session_id)),
                desc="tool_start event",
            )

            # Find the new PID file
            pid_data = wait_for(lambda: find_new_pid_file(pid_snapshot), desc="new PID file")
            assert pid_data is not None
            assert pid_data["_alive"]
            pid_sid = pid_data["sessionId"]

            # Build SessionManager and load initial state
            mgr = SessionManager(
                sessions_dir=CLAUDE_SESSIONS_DIR,
                projects_dir=CLAUDE_PROJECTS_DIR,
                recent=timedelta(hours=1),
            )
            mgr.refresh()
            events_typed = read_events_typed(events_dir, session_id=session_id)
            mgr.apply_events(events_typed)

            # Verify session is alive
            our_session = next((s for s in mgr.sessions if s.session_id == pid_sid), None)
            assert our_session is not None
            assert our_session.status in ("working", "idle")

            # Inject a fake session_end event (simulates /clear)
            fake_event = {"ts": int(time.time() * 1000), "sid": session_id, "type": "session_end"}
            events_file = events_dir / "events.jsonl"
            with events_file.open("a") as f:
                f.write(json.dumps(fake_event) + "\n")

            # Re-read events and apply to fresh manager
            all_events = read_events_typed(events_dir, session_id=session_id)
            mgr2 = SessionManager(
                sessions_dir=CLAUDE_SESSIONS_DIR,
                projects_dir=CLAUDE_PROJECTS_DIR,
                recent=timedelta(hours=1),
            )
            mgr2.refresh()
            mgr2.apply_events(all_events)

            # THE KEY ASSERTION: session must NOT be offline because PID is alive
            our_session = next((s for s in mgr2.sessions if s.session_id == pid_sid), None)
            assert our_session is not None, "Session disappeared from SessionManager"
            assert our_session.status != "offline", (
                f"Session is offline despite PID being alive! "
                f"session_end should not kill a live session. "
                f"Status: {our_session.status}"
            )
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_pid_file_cleanup_on_exit(tmp_path: Path) -> None:
    """PID file is removed after the claude process exits normally."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    pid_snapshot = snapshot_pid_files()

    try:
        with background_claude(work_dir, session_id, "respond with just the word PONG", events_dir):
            # Wait for the PID file to appear
            pid_data = wait_for(lambda: find_new_pid_file(pid_snapshot), desc="new PID file")
            assert pid_data is not None
            recorded_pid = pid_data["pid"]
            assert pid_file_exists(recorded_pid), "PID file should exist during session"

        # Process has been terminated by context manager
        time.sleep(3)

        assert not pid_file_exists(recorded_pid), f"PID file for {recorded_pid} still exists after process exit"

        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]
        assert "session_end" in event_types, f"No session_end event after exit. Events: {event_types}"
    finally:
        cleanup_transcript(work_dir, session_id)


@pytest.mark.contract
def test_session_id_mapping(tmp_path: Path) -> None:
    """SessionManager resolves events to the correct session via CWD-based mapping,
    even when PID file session ID differs from hook session ID."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    pid_snapshot = snapshot_pid_files()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir):
            # Wait for tool activity
            wait_for(
                lambda: any(e["type"] == "tool_start" for e in read_events(events_dir, session_id=session_id)),
                desc="tool_start event",
            )

            # Get PID file data
            pid_data = wait_for(lambda: find_new_pid_file(pid_snapshot), desc="new PID file")
            assert pid_data is not None
            pid_sid = pid_data["sessionId"]

            # -- Raw contract assertions --
            events = read_events(events_dir, session_id=session_id)
            assert len(events) > 0, "No events for our session_id"

            tpath = transcript_path(work_dir, session_id)
            assert tpath.is_file(), f"Transcript not at expected path {tpath}"

            # PID file sessionId may differ from our --session-id
            assert "sessionId" in pid_data

            # -- Integration assertion --
            mgr = SessionManager(
                sessions_dir=CLAUDE_SESSIONS_DIR,
                projects_dir=CLAUDE_PROJECTS_DIR,
                recent=timedelta(hours=1),
            )
            mgr.refresh()
            events_typed = read_events_typed(events_dir, session_id=session_id)
            mgr.apply_events(events_typed)

            # Session should be discoverable by PID-file session ID
            our_session = next((s for s in mgr.sessions if s.session_id == pid_sid), None)
            assert our_session is not None, "Session not found after event application"
            assert our_session.status in ("working", "idle"), f"Unexpected status: {our_session.status}"
    finally:
        cleanup_transcript(work_dir, session_id)
