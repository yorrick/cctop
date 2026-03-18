# iTerm2 Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow cctop users to press Enter on a session row to focus the iTerm2 tab/pane where that Claude Code session is running.

**Architecture:** New `ITermBridge` class in `sources/iterm2.py` with lazy imports. Connects to iTerm2's Python API on startup, maps Claude PIDs to iTerm2 panes via process tree walk-up, calls `session.async_activate()` to switch focus. Enter key rebound to focus, Space takes over expand/collapse.

**Tech Stack:** `iterm2` Python SDK, `psutil` for process tree walking, Textual keybindings

**Spec:** `docs/superpowers/specs/2026-03-17-iterm2-integration-design.md`

---

### Task 1: Add optional dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml:22-28`

- [ ] **Step 1: Add iterm2 optional extra**

Add after the `[project.urls]` section (after line 33):

```toml
[project.optional-dependencies]
iterm2 = ["iterm2", "psutil>=5.0"]
```

- [ ] **Step 2: Verify the extra resolves**

Run: `uv sync --extra iterm2`
Expected: Installs `iterm2`, `psutil`, `protobuf`, `websockets` without errors

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add iterm2 optional extra with iterm2 and psutil"
```

---

### Task 2: Create ITermBridge with connect()

**Files:**
- Create: `src/cctop/sources/iterm2.py`
- Create: `tests/test_sources_iterm2.py`

- [ ] **Step 1: Write the failing test for connect success**

```python
# tests/test_sources_iterm2.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cctop.sources.iterm2 import ITermBridge


@pytest.fixture(autouse=True)
def _reset_iterm2_globals() -> None:
    """Reset lazy-loaded module globals between tests."""
    import cctop.sources.iterm2 as mod

    mod._iterm2 = None
    mod._psutil = None


@pytest.mark.asyncio
async def test_connect_success() -> None:
    mock_connection = AsyncMock()
    mock_iterm2 = MagicMock()
    mock_iterm2.Connection.async_create = AsyncMock(return_value=mock_connection)

    bridge = ITermBridge()
    with patch.dict("sys.modules", {"iterm2": mock_iterm2, "psutil": MagicMock()}):
        await bridge.connect()

    assert bridge.available is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sources_iterm2.py::test_connect_success -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cctop.sources.iterm2'`

- [ ] **Step 3: Write the ITermBridge class with connect()**

```python
# src/cctop/sources/iterm2.py
"""Optional iTerm2 integration for focus switching."""

from __future__ import annotations

from loguru import logger

# Lazy-loaded modules — set by connect() if available
_iterm2: object | None = None
_psutil: object | None = None


class ITermBridge:
    """Optional iTerm2 integration for focus switching.

    Connects to iTerm2's Python API on startup.  If the iterm2 or psutil
    packages are not installed, or if iTerm2's API server is not enabled,
    the bridge silently disables itself.
    """

    def __init__(self) -> None:
        self._connection: object | None = None
        self._available: bool = False

    @property
    def available(self) -> bool:
        """Whether iTerm2 integration is available."""
        return self._available

    async def connect(self) -> None:
        """Try to connect to iTerm2 API. Sets available=False on failure."""
        global _iterm2, _psutil  # noqa: PLW0603
        try:
            import iterm2
            import psutil

            _iterm2 = iterm2
            _psutil = psutil
        except ImportError:
            logger.debug("iterm2 or psutil not installed — iTerm2 integration disabled")
            return

        try:
            self._connection = await iterm2.Connection.async_create()
            self._available = True
            logger.debug("Connected to iTerm2 API")
        except Exception as e:
            logger.debug("Failed to connect to iTerm2 API: {}", e)
            self._available = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sources_iterm2.py::test_connect_success -v`
Expected: PASS

- [ ] **Step 5: Write test for connect when packages not installed**

```python
@pytest.mark.asyncio
async def test_connect_import_error() -> None:
    bridge = ITermBridge()
    with patch.dict("sys.modules", {"iterm2": None, "psutil": None}):
        await bridge.connect()

    assert bridge.available is False
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_sources_iterm2.py::test_connect_import_error -v`
Expected: PASS

- [ ] **Step 7: Write test for connect when API server disabled**

```python
@pytest.mark.asyncio
async def test_connect_api_server_disabled() -> None:
    mock_iterm2 = MagicMock()
    mock_iterm2.Connection.async_create = AsyncMock(side_effect=ConnectionRefusedError("API server disabled"))

    bridge = ITermBridge()
    with patch.dict("sys.modules", {"iterm2": mock_iterm2, "psutil": MagicMock()}):
        await bridge.connect()

    assert bridge.available is False
```

- [ ] **Step 8: Run all tests so far**

Run: `uv run pytest tests/test_sources_iterm2.py -v`
Expected: 3 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/cctop/sources/iterm2.py tests/test_sources_iterm2.py
git commit -m "feat: add ITermBridge with connect() and lazy imports"
```

---

### Task 3: Add activate_session() to ITermBridge

**Files:**
- Modify: `src/cctop/sources/iterm2.py`
- Modify: `tests/test_sources_iterm2.py`

- [ ] **Step 1: Write the failing test for successful activation**

```python
@pytest.mark.asyncio
async def test_activate_session_success() -> None:
    """PID walk-up finds matching iTerm2 session and activates it."""
    mock_iterm_session = AsyncMock()
    mock_iterm_session.session_id = "iterm-session-1"

    # Mock psutil process chain: claude(100) -> fish(50) -> login(10)
    mock_login = MagicMock()
    mock_login.pid = 10
    mock_login.parent.return_value = None

    mock_fish = MagicMock()
    mock_fish.pid = 50
    mock_fish.parent.return_value = mock_login

    mock_claude = MagicMock()
    mock_claude.pid = 100
    mock_claude.parent.return_value = mock_fish

    # Mock iTerm2 app with one session whose root PID is 10
    mock_app = AsyncMock()
    mock_tab = MagicMock()
    mock_tab.sessions = [mock_iterm_session]
    mock_window = MagicMock()
    mock_window.tabs = [mock_tab]
    mock_app.windows = [mock_window]
    mock_iterm_session.async_get_variable = AsyncMock(return_value=10)

    bridge = ITermBridge()
    bridge._available = True
    bridge._connection = MagicMock()

    mock_iterm2_mod = MagicMock()
    mock_iterm2_mod.async_get_app = AsyncMock(return_value=mock_app)
    mock_psutil_mod = MagicMock()
    mock_psutil_mod.Process.return_value = mock_claude

    with (
        patch("cctop.sources.iterm2._iterm2", mock_iterm2_mod),
        patch("cctop.sources.iterm2._psutil", mock_psutil_mod),
    ):
        result = await bridge.activate_session(100)

    assert result is True
    mock_iterm_session.async_activate.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sources_iterm2.py::test_activate_session_success -v`
Expected: FAIL — `AttributeError: 'ITermBridge' object has no attribute 'activate_session'`

- [ ] **Step 3: Implement activate_session()**

Add to `ITermBridge` in `src/cctop/sources/iterm2.py`:

```python
    async def activate_session(self, claude_pid: int) -> bool:
        """Focus the iTerm2 pane running the given Claude Code process.

        Walks up the process tree from claude_pid to find a matching
        iTerm2 session, then activates (focuses) it.

        Returns True if focused, False if no matching pane found.
        """
        if not self._available or _iterm2 is None or _psutil is None:
            return False

        try:
            app = await _iterm2.async_get_app(self._connection)

            # Build root-PID -> iTerm2 session map
            pid_map: dict[int, object] = {}
            for window in app.windows:
                for tab in window.tabs:
                    for session in tab.sessions:
                        root_pid = await session.async_get_variable("pid")
                        pid_map[root_pid] = session

            # Walk up from Claude PID to find a match
            p = _psutil.Process(claude_pid)
            while p.pid > 1:
                if p.pid in pid_map:
                    await pid_map[p.pid].async_activate()
                    logger.debug("Focused iTerm2 session for PID {}", claude_pid)
                    return True
                parent = p.parent()
                if parent is None:
                    break
                p = parent

            logger.debug("No iTerm2 session found for PID {}", claude_pid)
            return False

        except Exception as e:
            logger.debug("iTerm2 activate failed for PID {}: {}", claude_pid, e)
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sources_iterm2.py::test_activate_session_success -v`
Expected: PASS

- [ ] **Step 5: Write test for no matching pane (orphaned session)**

```python
@pytest.mark.asyncio
async def test_activate_session_no_match() -> None:
    """PID walk-up finds no matching iTerm2 session."""
    mock_app = AsyncMock()
    mock_app.windows = []  # No windows/sessions

    # Mock psutil: process exists but no iTerm2 match
    mock_process = MagicMock()
    mock_process.pid = 100
    mock_process.parent.return_value = MagicMock(pid=1, parent=MagicMock(return_value=None))

    bridge = ITermBridge()
    bridge._available = True
    bridge._connection = MagicMock()

    mock_iterm2_mod = MagicMock()
    mock_iterm2_mod.async_get_app = AsyncMock(return_value=mock_app)
    mock_psutil_mod = MagicMock()
    mock_psutil_mod.Process.return_value = mock_process

    with (
        patch("cctop.sources.iterm2._iterm2", mock_iterm2_mod),
        patch("cctop.sources.iterm2._psutil", mock_psutil_mod),
    ):
        result = await bridge.activate_session(100)

    assert result is False
```

- [ ] **Step 6: Write test for dead PID (offline session)**

```python
@pytest.mark.asyncio
async def test_activate_session_dead_pid() -> None:
    """Dead PID raises NoSuchProcess, returns False."""
    bridge = ITermBridge()
    bridge._available = True
    bridge._connection = MagicMock()

    mock_iterm2_mod = MagicMock()
    mock_psutil_mod = MagicMock()
    mock_psutil_mod.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    mock_psutil_mod.Process.side_effect = mock_psutil_mod.NoSuchProcess(99999)

    with (
        patch("cctop.sources.iterm2._iterm2", mock_iterm2_mod),
        patch("cctop.sources.iterm2._psutil", mock_psutil_mod),
    ):
        result = await bridge.activate_session(99999)

    assert result is False
```

- [ ] **Step 7: Write test for not available (no-op)**

```python
@pytest.mark.asyncio
async def test_activate_session_not_available() -> None:
    """When bridge is not available, returns False immediately."""
    bridge = ITermBridge()
    assert bridge.available is False

    result = await bridge.activate_session(12345)
    assert result is False
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest tests/test_sources_iterm2.py -v`
Expected: 7 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/cctop/sources/iterm2.py tests/test_sources_iterm2.py
git commit -m "feat: add activate_session() with PID walk-up and focus switching"
```

---

### Task 4: Wire ITermBridge into CctopApp

**Files:**
- Modify: `src/cctop/app.py:8-14,58-80`

Note: This task must come BEFORE keybinding changes (Task 5), because `action_focus_iterm` accesses `self.app._iterm_bridge`.

- [ ] **Step 1: Import and instantiate ITermBridge**

In `src/cctop/app.py`, add import at top:

```python
from cctop.sources.iterm2 import ITermBridge
```

Update `__init__`:

```python
    def __init__(self, recent: timedelta = timedelta(0), **kwargs) -> None:
        super().__init__(**kwargs)
        self._manager = SessionManager(recent=recent)
        self._tailer = EventsTailer(Path.home() / ".cctop" / "data" / "events.jsonl")
        self._sort_index = 0
        self._iterm_bridge = ITermBridge()
```

- [ ] **Step 2: Call connect() in on_mount()**

Update `on_mount()` to connect the bridge:

```python
    async def on_mount(self) -> None:
        self._tailer.cleanup_if_needed()
        if not self._tailer.hooks_installed:
            self.notify(
                "Hooks not installed — run 'cctop install' for real-time status.",
                severity="warning",
                timeout=10,
            )
        await self._iterm_bridge.connect()
        self.set_interval(2, self._poll_fast)
        self.set_interval(10, self._poll_slow)
        self._poll_fast()
        await self._poll_slow()
```

- [ ] **Step 3: Update help text in app.py**

In `src/cctop/app.py`, update `action_show_help()`:

```python
        help_text = (
            "cctop — Claude Code session monitor\n\n"
            "↑/↓ or k/j   Navigate sessions\n"
            "Space         Expand / collapse\n"
            "Enter         Focus iTerm2 pane\n"
            "F6 or >/<     Cycle sort mode\n"
            "/             Filter (coming soon)\n"
            "?/h           This help\n"
            "q / F10       Quit"
        )
```

- [ ] **Step 4: Run ruff and pyright on app.py**

Run: `uv run ruff format src/cctop/app.py && uv run ruff check --fix src/cctop/app.py && uv run pyright src/cctop/app.py`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/cctop/app.py
git commit -m "feat: wire ITermBridge into CctopApp — connect on mount"
```

---

### Task 5: Rebind keybindings — Space for expand/collapse, Enter for focus

**Files:**
- Modify: `src/cctop/widgets/session_list.py:19-26`
- Modify: `src/cctop/widgets/footer.py:10-17`

Depends on Task 4 (`_iterm_bridge` must exist on `CctopApp` before `action_focus_iterm` can reference it).

- [ ] **Step 1: Update SessionList.BINDINGS**

In `src/cctop/widgets/session_list.py`, change line 24 and add Space binding:

```python
    BINDINGS = [
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("space", "toggle_expand", "Expand/Collapse"),
        Binding("enter", "focus_iterm", "Focus pane"),
        Binding("r", "regenerate_summary", "Regenerate summary"),
    ]
```

- [ ] **Step 2: Add action_focus_iterm() method**

Add to `SessionList` class in `src/cctop/widgets/session_list.py`:

```python
    async def action_focus_iterm(self) -> None:
        """Focus the iTerm2 pane running the selected session."""
        if not self._sessions:
            return
        if not self.app._iterm_bridge.available:  # type: ignore[attr-defined]
            return
        session = self._sessions[self._cursor]
        focused = await self.app._iterm_bridge.activate_session(session.pid)  # type: ignore[attr-defined]
        if not focused:
            self.app.notify("No iTerm2 pane found for this session")
```

- [ ] **Step 3: Update footer labels**

In `src/cctop/widgets/footer.py`, update the shortcuts list:

```python
        shortcuts = [
            ("↑↓", "navigate"),
            ("Space", "expand/collapse"),
            ("Enter", "focus pane"),
            ("F6", "sort"),
            ("/", "filter"),
            ("?", "help"),
            ("q", "quit"),
        ]
```

- [ ] **Step 4: Run ruff format and ruff check**

Run: `uv run ruff format src/cctop/widgets/session_list.py src/cctop/widgets/footer.py && uv run ruff check --fix src/cctop/widgets/session_list.py src/cctop/widgets/footer.py`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/cctop/widgets/session_list.py src/cctop/widgets/footer.py
git commit -m "feat: rebind Enter to focus iTerm2 pane, Space to expand/collapse"
```

---

### Task 6: Add keybinding tests

**Files:**
- Create: `tests/widgets/test_session_list.py`

Note: `tests/widgets/__init__.py` already exists.

- [ ] **Step 1: Write test that Space triggers expand/collapse**

```python
# tests/widgets/test_session_list.py
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cctop.models import Session
from cctop.widgets.session_list import SessionList


def _make_session(session_id: str = "abc-123", pid: int = 12345) -> Session:
    return Session(
        session_id=session_id,
        pid=pid,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="idle",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_activity=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_space_binding_maps_to_toggle_expand() -> None:
    """Verify Space is bound to action_toggle_expand."""
    bindings = {b.key: b.action for b in SessionList.BINDINGS}
    assert bindings["space"] == "toggle_expand"


def test_enter_binding_maps_to_focus_iterm() -> None:
    """Verify Enter is bound to action_focus_iterm."""
    bindings = {b.key: b.action for b in SessionList.BINDINGS}
    assert bindings["enter"] == "focus_iterm"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/widgets/test_session_list.py -v`
Expected: 2 tests PASS

- [ ] **Step 3: Write test for action_focus_iterm when bridge unavailable**

```python
@pytest.mark.asyncio
async def test_action_focus_iterm_bridge_unavailable() -> None:
    """When iTerm2 bridge is not available, action_focus_iterm is a no-op."""
    widget = SessionList()
    widget._sessions = [_make_session()]
    widget._cursor = 0

    mock_bridge = MagicMock()
    mock_bridge.available = False

    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_bridge.activate_session.assert_not_called()
```

- [ ] **Step 4: Write test for action_focus_iterm success (no notification)**

```python
@pytest.mark.asyncio
async def test_action_focus_iterm_success_no_notification() -> None:
    """When activate_session returns True, no notification is shown."""
    widget = SessionList()
    widget._sessions = [_make_session()]
    widget._cursor = 0

    mock_bridge = MagicMock()
    mock_bridge.available = True
    mock_bridge.activate_session = AsyncMock(return_value=True)

    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_bridge.activate_session.assert_awaited_once_with(12345)
    mock_app.notify.assert_not_called()
```

- [ ] **Step 5: Write test for action_focus_iterm no match (notification shown)**

```python
@pytest.mark.asyncio
async def test_action_focus_iterm_no_match_shows_notification() -> None:
    """When activate_session returns False, a notification is shown."""
    widget = SessionList()
    widget._sessions = [_make_session()]
    widget._cursor = 0

    mock_bridge = MagicMock()
    mock_bridge.available = True
    mock_bridge.activate_session = AsyncMock(return_value=False)

    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_app.notify.assert_called_once_with("No iTerm2 pane found for this session")
```

- [ ] **Step 6: Write test for action_focus_iterm with empty session list**

```python
@pytest.mark.asyncio
async def test_action_focus_iterm_empty_sessions() -> None:
    """When session list is empty, action_focus_iterm is a no-op."""
    widget = SessionList()
    widget._sessions = []

    mock_bridge = MagicMock()
    mock_app = MagicMock()
    mock_app._iterm_bridge = mock_bridge

    with patch.object(type(widget), "app", new_callable=lambda: property(lambda self: mock_app)):
        await widget.action_focus_iterm()

    mock_bridge.activate_session.assert_not_called()
```

- [ ] **Step 7: Run all keybinding tests**

Run: `uv run pytest tests/widgets/test_session_list.py -v`
Expected: 6 tests PASS

- [ ] **Step 8: Commit**

```bash
git add tests/widgets/test_session_list.py
git commit -m "test: add keybinding tests for Enter/Space rebinding"
```

---

### Task 7: Final validation

**Files:** (none — validation only)

- [ ] **Step 1: Run full quality checks**

Run: `uv run ruff format src/ tests/ && uv run ruff check --fix src/ tests/ && uv run pyright && uv run pytest`
Expected: All checks pass

- [ ] **Step 2: Manual smoke test**

Run cctop with the iterm2 extra installed:

```bash
uv run cctop --recent 1h
```

Verify:
1. Footer shows updated keybindings (Space for expand/collapse, Enter for focus pane)
2. Space expands/collapses session detail
3. Enter switches iTerm2 focus to the selected session's pane
4. Enter on an orphaned/offline session shows toast "No iTerm2 pane found for this session"
5. Help (?) shows updated keybinding text

- [ ] **Step 3: Commit any final fixes if needed**
