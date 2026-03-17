# Contract Tests Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add contract tests that run real Claude Code sessions to verify cctop correctly ingests Claude Code's file/event artifacts.

**Architecture:** Each test runs `claude --print` via subprocess with a deterministic `--session-id`, an isolated events directory (`CCTOP_DATA_DIR`), and `tmp_path` as cwd. Tests assert on both raw artifacts (events, transcripts, PID files) and `SessionManager` integration. Test 4 proves (and will require fixing) the `session_end` != process death bug in `merger.py`.

**Tech Stack:** pytest, subprocess, `@pytest.mark.contract` marker

**Spec:** `docs/superpowers/specs/2026-03-17-contract-tests-design.md`

---

### Task 1: Add pytest marker and test helpers

**Files:**
- Modify: `pyproject.toml` (add `[tool.pytest.ini_options]` section)
- Create: `tests/test_contract.py`

- [ ] **Step 1: Add contract marker to pyproject.toml**

Add after the `[tool.pyright]` section:

```toml
[tool.pytest.ini_options]
markers = ["contract: contract tests that run real Claude Code sessions (require claude CLI, cost tokens)"]
addopts = "-m 'not contract'"
```

- [ ] **Step 2: Create test_contract.py with helpers**

Create `tests/test_contract.py` with all test infrastructure:

```python
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
POLL_TIMEOUT = 15.0
POLL_INTERVAL = 0.5


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


def read_events(events_dir: Path, *, session_id: str | None = None) -> list[dict]:
    """Read events from the isolated events.jsonl, optionally filtering by session ID."""
    events_file = events_dir / "events.jsonl"
    if not events_file.is_file():
        return []
    events = []
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


def find_pid_file_by_cwd(cwd: Path) -> dict | None:
    """Find a PID file whose cwd matches the given path. Returns parsed data or None."""
    if not CLAUDE_SESSIONS_DIR.is_dir():
        return None
    for path in CLAUDE_SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text().split("\n", 1)[0])
            if Path(data["cwd"]) == cwd:
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


def read_transcript_messages(work_dir: Path, session_id: str) -> list[dict]:
    """Read transcript and return user/assistant messages."""
    path = transcript_path(work_dir, session_id)
    if not path.is_file():
        return []
    messages = []
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
    dangerously_skip_permissions: bool = False,
    timeout: int = SHORT_SESSION_TIMEOUT,
) -> subprocess.CompletedProcess:
    """Run a claude --print session synchronously."""
    cmd = ["claude", "--print"]
    if resume:
        cmd += ["--resume", session_id]
    else:
        cmd += ["--session-id", session_id]
    if dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
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
) -> Generator[subprocess.Popen]:
    """Start claude --print in background with --dangerously-skip-permissions.

    Yields Popen, sends SIGTERM on exit.
    """
    cmd = [
        "claude", "--print",
        "--session-id", session_id,
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


def build_session_manager(events_dir: Path) -> tuple[SessionManager, EventsTailer]:
    """Build a SessionManager pointed at real ~/.claude dirs and an isolated EventsTailer."""
    mgr = SessionManager(
        sessions_dir=CLAUDE_SESSIONS_DIR,
        projects_dir=CLAUDE_PROJECTS_DIR,
        recent=timedelta(hours=1),
    )
    tailer = EventsTailer(events_dir / "events.jsonl")
    return mgr, tailer


```

- [ ] **Step 3: Verify the module imports work**

Run: `cd /Users/yorrickjansen/work/cctop && uv run python -c "from tests.test_contract import wait_for, read_events; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /Users/yorrickjansen/work/cctop
git add pyproject.toml tests/test_contract.py
git commit -m "feat: add contract test infrastructure and helpers"
```

---

### Task 2: test_basic_lifecycle

**Files:**
- Modify: `tests/test_contract.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_contract.py`:

```python
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

        # Required events exist
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
        assert start_event["cwd"] == str(work_dir), (
            f"session_start cwd mismatch: {start_event['cwd']} != {work_dir}"
        )

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
        # Give it a moment to fully terminate.
        time.sleep(2)

        # SessionManager with recent=0 should not show dead sessions
        mgr = SessionManager(
            sessions_dir=CLAUDE_SESSIONS_DIR,
            projects_dir=CLAUDE_PROJECTS_DIR,
        )
        mgr.refresh()
        session_ids = [s.session_id for s in mgr.sessions]
        # The PID-file session ID may differ from our --session-id,
        # but either way the dead process should be evicted.
        # Just verify no session points to our work_dir.
        session_cwds = [str(s.cwd) for s in mgr.sessions]
        assert str(work_dir) not in session_cwds, (
            f"Dead session still visible in SessionManager for {work_dir}"
        )
    finally:
        cleanup_transcript(work_dir, session_id)
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py::test_basic_lifecycle -m contract -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract.py
git commit -m "test: add contract test for basic session lifecycle"
```

---

### Task 3: test_session_resumption

**Files:**
- Modify: `tests/test_contract.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_contract.py`:

```python
@pytest.mark.contract
def test_session_resumption(tmp_path: Path) -> None:
    """--resume reuses the same session ID and appends to the same transcript."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        # First session
        result1 = run_claude_print(work_dir, session_id, "respond with just the word PONG", events_dir)
        assert result1.returncode == 0, f"First session failed: {result1.stderr}"

        # Wait for process cleanup
        time.sleep(2)

        # Second session via --resume
        result2 = run_claude_print(
            work_dir, session_id, "respond with just the word PING", events_dir, resume=True
        )
        assert result2.returncode == 0, f"Resume session failed: {result2.stderr}"

        # -- Raw contract assertions --
        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]

        # Two session_start and two session_end events
        assert event_types.count("session_start") == 2, (
            f"Expected 2 session_start events, got {event_types.count('session_start')}: {event_types}"
        )
        assert event_types.count("session_end") == 2, (
            f"Expected 2 session_end events, got {event_types.count('session_end')}: {event_types}"
        )

        # Same transcript file, appended to
        tpath = transcript_path(work_dir, session_id)
        assert tpath.is_file(), f"Transcript not found at {tpath}"

        messages = read_transcript_messages(work_dir, session_id)
        user_msgs = [m for m in messages if m["type"] == "user"]
        asst_msgs = [m for m in messages if m["type"] == "assistant"]
        assert len(user_msgs) >= 2, f"Expected at least 2 user messages, got {len(user_msgs)}"
        assert len(asst_msgs) >= 2, f"Expected at least 2 assistant messages, got {len(asst_msgs)}"
    finally:
        cleanup_transcript(work_dir, session_id)
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py::test_session_resumption -m contract -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract.py
git commit -m "test: add contract test for session resumption"
```

---

### Task 4: test_long_lived_session

**Files:**
- Modify: `tests/test_contract.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_contract.py`:

```python
LONG_RUNNING_PROMPT = (
    "Write a bash script that prints hello every 2 seconds for 20 seconds. "
    "Run it."
)


@pytest.mark.contract
def test_long_lived_session(tmp_path: Path) -> None:
    """While a session is running, SessionManager sees it as working/idle, not offline."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir) as proc:
            # Wait for session_start event
            wait_for(
                lambda: any(
                    e["type"] == "session_start"
                    for e in read_events(events_dir, session_id=session_id)
                ),
                desc="session_start event",
            )

            # Wait for tool_start event (Bash tool)
            wait_for(
                lambda: any(
                    e["type"] == "tool_start"
                    for e in read_events(events_dir, session_id=session_id)
                ),
                desc="tool_start event",
            )

            # PID file should exist
            assert proc.pid is not None
            # The PID file might be for the parent process or a child;
            # find it by cwd matching
            pid_data = find_pid_file_by_cwd(work_dir)
            assert pid_data is not None, "No PID file found for session work_dir"
            assert pid_data["_alive"], "PID should be alive"

            # -- Integration assertion --
            mgr = SessionManager(
                sessions_dir=CLAUDE_SESSIONS_DIR,
                projects_dir=CLAUDE_PROJECTS_DIR,
                recent=timedelta(hours=1),
            )
            mgr.refresh()

            events_typed = read_events_typed(events_dir, session_id=session_id)
            mgr.apply_events(events_typed)

            # Find our session by cwd
            our_sessions = [s for s in mgr.sessions if str(s.cwd) == str(work_dir)]
            assert len(our_sessions) >= 1, (
                f"Session not found in SessionManager. All cwds: {[str(s.cwd) for s in mgr.sessions]}"
            )
            session = our_sessions[0]
            assert session.status in ("working", "idle"), (
                f"Session should be working or idle, got: {session.status}"
            )

        # After context manager kills the process, wait for cleanup
        time.sleep(3)

        # PID file should be cleaned up
        if pid_data:
            assert not pid_file_exists(pid_data["pid"]), "PID file should be removed after exit"

        # session_end event should exist
        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]
        assert "session_end" in event_types, f"No session_end after exit. Events: {event_types}"
    finally:
        cleanup_transcript(work_dir, session_id)
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py::test_long_lived_session -m contract -v -s`
Expected: PASS (may take 30-60s)

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract.py
git commit -m "test: add contract test for long-lived session status"
```

---

### Task 5: test_session_end_does_not_mean_process_dead (bug fix)

This is the key test that **proves the bug** and then fixes it. The test is written first, verified to fail, then the bug is fixed.

**Files:**
- Modify: `tests/test_contract.py`
- Modify: `src/cctop/sources/merger.py:228-232`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_contract.py`:

```python
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

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir) as proc:
            # Wait for session to be active
            wait_for(
                lambda: any(
                    e["type"] == "tool_start"
                    for e in read_events(events_dir, session_id=session_id)
                ),
                desc="tool_start event",
            )

            # Find the PID file to get the PID-file session ID
            pid_data = wait_for(
                lambda: find_pid_file_by_cwd(work_dir),
                desc="PID file for work_dir",
            )
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
            our_sessions = [s for s in mgr.sessions if str(s.cwd) == str(work_dir)]
            assert len(our_sessions) >= 1
            assert our_sessions[0].status in ("working", "idle")

            # Inject a fake session_end event (simulates /clear)
            fake_event = {
                "ts": int(time.time() * 1000),
                "sid": session_id,
                "type": "session_end",
            }
            events_file = events_dir / "events.jsonl"
            with events_file.open("a") as f:
                f.write(json.dumps(fake_event) + "\n")

            # Re-read events and apply
            all_events = read_events_typed(events_dir, session_id=session_id)
            # Create fresh manager to avoid stale state
            mgr2 = SessionManager(
                sessions_dir=CLAUDE_SESSIONS_DIR,
                projects_dir=CLAUDE_PROJECTS_DIR,
                recent=timedelta(hours=1),
            )
            mgr2.refresh()
            mgr2.apply_events(all_events)

            # THE KEY ASSERTION: session must NOT be offline because PID is alive
            our_sessions = [s for s in mgr2.sessions if str(s.cwd) == str(work_dir)]
            assert len(our_sessions) >= 1, "Session disappeared from SessionManager"
            assert our_sessions[0].status != "offline", (
                f"Session is offline despite PID being alive! "
                f"session_end should not kill a live session. "
                f"Status: {our_sessions[0].status}"
            )
    finally:
        cleanup_transcript(work_dir, session_id)
```

- [ ] **Step 2: Run to verify it FAILS**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py::test_session_end_does_not_mean_process_dead -m contract -v -s`
Expected: FAIL with "Session is offline despite PID being alive!"

- [ ] **Step 3: Fix the bug in merger.py**

In `src/cctop/sources/merger.py`, modify the `session_end` case in `apply_events()` (lines 228-232) to cross-check PID liveness before marking offline:

```python
                case "session_end":
                    # Only mark offline if the process is actually dead.
                    # session_end also fires on /clear, which resets the
                    # conversation but keeps the process alive.
                    from cctop.sources.sessions import is_pid_alive

                    if not is_pid_alive(session.pid):
                        session.status = "offline"
                        session.ended_at = now_ts
                    session.last_activity = now_ts
                    self._stopped_sessions.discard(session.session_id)
```

- [ ] **Step 4: Run the test again to verify it PASSES**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py::test_session_end_does_not_mean_process_dead -m contract -v -s`
Expected: PASS

- [ ] **Step 5: Run existing unit tests to verify no regressions**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/ -m "not contract" -v`
Expected: All existing tests PASS

- [ ] **Step 6: Run ruff + pyright**

Run: `cd /Users/yorrickjansen/work/cctop && uv run ruff check src/cctop/sources/merger.py && uv run pyright src/cctop/sources/merger.py`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/cctop/sources/merger.py tests/test_contract.py
git commit -m "fix: session_end with alive PID should not mark session offline

session_end fires on /clear (conversation reset) not just process exit.
Cross-check PID liveness before transitioning to offline."
```

---

### Task 6: test_pid_file_cleanup_on_exit

**Files:**
- Modify: `tests/test_contract.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_contract.py`:

```python
@pytest.mark.contract
def test_pid_file_cleanup_on_exit(tmp_path: Path) -> None:
    """PID file is removed after the claude process exits normally."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        # Use background_claude so we can capture the PID before exit
        with background_claude(work_dir, session_id, "respond with just the word PONG", events_dir) as proc:
            # Wait for the PID file to appear
            pid_data = wait_for(
                lambda: find_pid_file_by_cwd(work_dir),
                desc="PID file to appear",
            )
            recorded_pid = pid_data["pid"]
            assert pid_file_exists(recorded_pid), "PID file should exist during session"

        # Process has been terminated by context manager
        time.sleep(3)

        # PID file should be cleaned up
        assert not pid_file_exists(recorded_pid), (
            f"PID file for {recorded_pid} still exists after process exit"
        )

        # session_end event should have been emitted
        events = read_events(events_dir, session_id=session_id)
        event_types = [e["type"] for e in events]
        assert "session_end" in event_types, f"No session_end event after exit. Events: {event_types}"
    finally:
        cleanup_transcript(work_dir, session_id)
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py::test_pid_file_cleanup_on_exit -m contract -v -s`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract.py
git commit -m "test: add contract test for PID file cleanup on exit"
```

---

### Task 7: test_session_id_mapping

**Files:**
- Modify: `tests/test_contract.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_contract.py`:

```python
@pytest.mark.contract
def test_session_id_mapping(tmp_path: Path) -> None:
    """SessionManager resolves events to the correct session via CWD-based mapping,
    even when PID file session ID differs from hook session ID."""
    session_id = str(uuid.uuid4())
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    try:
        with background_claude(work_dir, session_id, LONG_RUNNING_PROMPT, events_dir) as proc:
            # Wait for tool activity
            wait_for(
                lambda: any(
                    e["type"] == "tool_start"
                    for e in read_events(events_dir, session_id=session_id)
                ),
                desc="tool_start event",
            )

            # Get PID file data
            pid_data = wait_for(
                lambda: find_pid_file_by_cwd(work_dir),
                desc="PID file for work_dir",
            )
            pid_sid = pid_data["sessionId"]

            # -- Raw contract assertions --
            # Hook events use our --session-id
            events = read_events(events_dir, session_id=session_id)
            assert len(events) > 0, "No events for our session_id"

            # Transcript is named after our --session-id
            tpath = transcript_path(work_dir, session_id)
            assert tpath.is_file(), f"Transcript not at expected path {tpath}"

            # PID file sessionId may differ from our --session-id
            # (this documents the contract — the assertion is that the field exists,
            # not that it matches)
            assert "sessionId" in pid_data

            # -- Integration assertion --
            # SessionManager must resolve events to the session via CWD mapping
            mgr = SessionManager(
                sessions_dir=CLAUDE_SESSIONS_DIR,
                projects_dir=CLAUDE_PROJECTS_DIR,
                recent=timedelta(hours=1),
            )
            mgr.refresh()
            events_typed = read_events_typed(events_dir, session_id=session_id)
            mgr.apply_events(events_typed)

            # Session should be discoverable and have metadata from transcript
            our_sessions = [s for s in mgr.sessions if str(s.cwd) == str(work_dir)]
            assert len(our_sessions) >= 1, "Session not found after CWD-based event resolution"

            session = our_sessions[0]
            # After event application, session should have activity
            assert session.status in ("working", "idle"), f"Unexpected status: {session.status}"
            # Transcript metadata should be associated (message count > 0)
            assert session.message_count >= 1, (
                f"Message count not populated after CWD mapping: {session.message_count}"
            )
    finally:
        cleanup_transcript(work_dir, session_id)
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py::test_session_id_mapping -m contract -v -s`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_contract.py
git commit -m "test: add contract test for session ID mapping across PID/hook mismatch"
```

---

### Task 8: Final validation

**Files:** None (validation only)

- [ ] **Step 1: Run ALL contract tests**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/test_contract.py -m contract -v -s`
Expected: All 6 tests PASS

- [ ] **Step 2: Run full test suite (unit + contract)**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/ -v`
Expected: All unit tests PASS, contract tests not collected (filtered by `addopts = "-m 'not contract'"`)

- [ ] **Step 3: Run ruff + pyright on all changed files**

Run: `cd /Users/yorrickjansen/work/cctop && uv run ruff check tests/test_contract.py src/cctop/sources/merger.py && uv run ruff format --check tests/test_contract.py src/cctop/sources/merger.py && uv run pyright tests/test_contract.py src/cctop/sources/merger.py`
Expected: No errors

- [ ] **Step 4: Verify contract tests are not collected by default**

Run: `cd /Users/yorrickjansen/work/cctop && uv run pytest tests/ -v 2>&1 | grep -c contract`
Expected: `0` (no contract tests collected or run)
