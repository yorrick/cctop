# cctop Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live Textual TUI that monitors all Claude Code sessions with real-time status from hooks.

**Architecture:** Four data sources (session files, sessions-index, hook events, gh PR lookup) are read by a polling loop and merged into Pydantic Session models. A Textual app renders them as an expandable/collapsible list. A Typer CLI provides install/uninstall/launch commands. A bash hook script captures real-time tool events.

**Tech Stack:** Python 3.12+, uv, Textual, Typer, Pydantic, loguru, ruff, pyright, pytest

**Spec:** `docs/superpowers/specs/2026-03-17-cctop-design.md`

---

## File Structure

**Note:** The spec uses a flat `cctop/` layout. This plan uses `src/cctop/` (src layout) which is standard for uv projects with `--lib`.

```
pyproject.toml                    # uv project config, dependencies, entry point
src/cctop/__init__.py             # Package init
src/cctop/cli.py                  # Typer CLI: main, install, uninstall commands
src/cctop/app.py                  # Textual App with polling workers
src/cctop/models.py               # Pydantic Session model + event models
src/cctop/duration.py             # --recent duration string parser
src/cctop/sources/__init__.py
src/cctop/sources/sessions.py     # ~/.claude/sessions/ reader + PID liveness
src/cctop/sources/index.py        # sessions-index.json reader
src/cctop/sources/events.py       # events.jsonl tailer
src/cctop/sources/github.py       # gh PR lookup (background, cached)
src/cctop/sources/merger.py       # Merges all sources into Session list
src/cctop/hooks/__init__.py
src/cctop/hooks/install.py        # Hook install/uninstall logic
src/cctop/hooks/cctop-hook.sh     # Bash hook script template
src/cctop/widgets/__init__.py
src/cctop/widgets/session_list.py # Main scrollable list widget
src/cctop/widgets/session_row.py  # Collapsed row widget
src/cctop/widgets/session_detail.py # Expanded detail view
src/cctop/widgets/header.py       # Top bar with counts + sort
src/cctop/widgets/footer.py       # Keyboard shortcut help bar
tests/__init__.py
tests/test_models.py
tests/test_duration.py
tests/test_sources_sessions.py
tests/test_sources_index.py
tests/test_sources_events.py
tests/test_sources_github.py
tests/test_sources_merger.py
tests/test_hooks_install.py
tests/test_events_cleanup.py
tests/test_app.py                 # Textual app snapshot/pilot tests
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/cctop/__init__.py`
- Create: `src/cctop/cli.py`
- Create: `tests/__init__.py`
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Initialize uv project**

Run:
```bash
cd /Users/yorrickjansen/work/cctop
uv init --lib --package --name cctop
```

- [ ] **Step 2: Configure pyproject.toml**

Set up `pyproject.toml` with:
- `requires-python = ">=3.12"`
- Dependencies: `textual>=3.0`, `typer>=0.15`, `pydantic>=2.0`, `loguru`
- Dev dependencies: `pytest`, `pytest-asyncio`, `ruff`, `pyright`, `pre-commit`, `textual-dev`
- Entry point: `[project.scripts] cctop = "cctop.cli:app"`
- Ruff config: `line-length = 120`, `target-version = "py312"`

Run:
```bash
uv add textual typer pydantic loguru
uv add --dev pytest pytest-asyncio ruff pyright pre-commit textual-dev
```

- [ ] **Step 3: Create minimal CLI entry point**

`src/cctop/__init__.py`:
```python
"""cctop — A htop-like TUI for monitoring Claude Code sessions."""
```

`src/cctop/cli.py`:
```python
import typer

app = typer.Typer(help="cctop — monitor Claude Code sessions in real-time")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    recent: str = typer.Option("0", help="Include sessions ended within this duration (e.g. 30m, 1h, 2h, 1d)"),
) -> None:
    """Launch the cctop TUI."""
    if ctx.invoked_subcommand is None:
        typer.echo(f"cctop TUI would launch here (recent={recent})")


@app.command()
def install() -> None:
    """Install cctop hooks into Claude Code settings."""
    typer.echo("install placeholder")


@app.command()
def uninstall() -> None:
    """Remove cctop hooks and clean up."""
    typer.echo("uninstall placeholder")
```

- [ ] **Step 4: Create pre-commit config**

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.2
    hooks:
      - id: ruff-format
      - id: ruff
        args: [--fix]
  - repo: local
    hooks:
      - id: pyright
        name: pyright
        entry: uv run pyright
        language: system
        types: [python]
        pass_filenames: false
```

Run:
```bash
uv run pre-commit install
```

- [ ] **Step 5: Verify CLI works**

Run:
```bash
uv run cctop
uv run cctop install
uv run cctop uninstall
```

Expected: Each prints its placeholder message.

- [ ] **Step 6: Run quality checks**

Run:
```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run pyright src/ tests/
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/ tests/ .pre-commit-config.yaml .python-version
git commit -m "feat: scaffold cctop project with CLI entry point"
```

---

### Task 2: Duration Parser

**Files:**
- Create: `src/cctop/duration.py`
- Create: `tests/test_duration.py`

- [ ] **Step 1: Write failing tests**

`tests/test_duration.py`:
```python
from datetime import timedelta

import pytest

from cctop.duration import parse_duration


def test_parse_zero() -> None:
    assert parse_duration("0") == timedelta(0)


def test_parse_minutes() -> None:
    assert parse_duration("30m") == timedelta(minutes=30)


def test_parse_hours() -> None:
    assert parse_duration("2h") == timedelta(hours=2)


def test_parse_days() -> None:
    assert parse_duration("1d") == timedelta(days=1)


def test_parse_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration("abc")


def test_parse_empty_raises() -> None:
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration("")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_duration.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement duration parser**

`src/cctop/duration.py`:
```python
import re
from datetime import timedelta

_DURATION_RE = re.compile(r"^(\d+)([mhd])$")


def parse_duration(value: str) -> timedelta:
    """Parse a duration string like '30m', '2h', '1d' into a timedelta.

    '0' means zero duration.
    """
    if value == "0":
        return timedelta(0)

    match = _DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid duration: {value!r}. Use format like 30m, 2h, 1d, or 0.")

    amount = int(match.group(1))
    unit = match.group(2)

    match unit:
        case "m":
            return timedelta(minutes=amount)
        case "h":
            return timedelta(hours=amount)
        case "d":
            return timedelta(days=amount)
        case _:
            raise ValueError(f"Invalid duration unit: {unit!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_duration.py -v`
Expected: All 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cctop/duration.py tests/test_duration.py
git commit -m "feat: add duration string parser for --recent flag"
```

---

### Task 3: Pydantic Models

**Files:**
- Create: `src/cctop/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

`tests/test_models.py`:
```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cctop.models import Event, Session


def test_session_idle_duration_when_working() -> None:
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="working",
        started_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.idle_duration == timedelta(0)


def test_session_idle_duration_when_idle() -> None:
    last = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="idle",
        started_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        last_activity=last,
    )
    assert s.idle_duration >= timedelta(minutes=4)


def test_session_idle_duration_when_offline() -> None:
    last = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    ended = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="offline",
        started_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        last_activity=last,
        ended_at=ended,
    )
    # Frozen at death time: ended_at - last_activity
    assert timedelta(minutes=4) <= s.idle_duration <= timedelta(minutes=6)


def test_session_duration_when_alive() -> None:
    start = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="idle",
        started_at=start,
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.session_duration >= timedelta(hours=1, minutes=59)


def test_session_duration_when_offline() -> None:
    start = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    ended = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/tmp/test"),
        project_name="test",
        status="offline",
        started_at=start,
        last_activity=start,
        ended_at=ended,
    )
    assert timedelta(minutes=59) <= s.session_duration <= timedelta(hours=1, minutes=1)


def test_worktree_name_extracted() -> None:
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/Users/foo/work/project/.worktrees/dev-loop/issue-349"),
        project_name="project",
        status="idle",
        started_at=datetime.now(tz=timezone.utc),
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.worktree_name == "issue-349"


def test_worktree_name_none_for_regular_path() -> None:
    s = Session(
        session_id="abc",
        pid=123,
        cwd=Path("/Users/foo/work/project"),
        project_name="project",
        status="idle",
        started_at=datetime.now(tz=timezone.utc),
        last_activity=datetime.now(tz=timezone.utc),
    )
    assert s.worktree_name is None


def test_event_tool_start() -> None:
    e = Event(ts=1000, sid="abc", type="tool_start", tool="Bash", cwd="/tmp")
    assert e.type == "tool_start"
    assert e.tool == "Bash"


def test_event_stop() -> None:
    e = Event(ts=1000, sid="abc", type="stop")
    assert e.tool is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement models**

`src/cctop/models.py`:
```python
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, computed_field, model_validator


class Event(BaseModel):
    """A single hook event from events.jsonl."""

    ts: int
    sid: str
    type: Literal["tool_start", "tool_end", "stop", "session_start", "session_end"]
    tool: str | None = None
    ok: bool | None = None
    cwd: str | None = None


class Session(BaseModel):
    """A Claude Code session with merged data from all sources."""

    session_id: str
    pid: int
    cwd: Path
    project_name: str
    worktree_name: str | None = None
    git_branch: str | None = None
    pr_url: str | None = None
    pr_title: str | None = None
    status: Literal["working", "idle", "offline"]
    current_tool: str | None = None
    started_at: datetime
    last_activity: datetime
    ended_at: datetime | None = None
    message_count: int = 0
    summary: str | None = None
    first_prompt: str | None = None

    @model_validator(mode="after")
    def _extract_worktree_name(self) -> "Session":
        """Extract worktree name from cwd if it contains a worktrees segment."""
        parts = self.cwd.parts
        for i, part in enumerate(parts):
            if part in ("worktrees", ".worktrees") and i + 1 < len(parts):
                # Take the last segment after the worktrees dir
                # e.g. .worktrees/dev-loop/issue-349 -> issue-349
                self.worktree_name = parts[-1] if len(parts) > i + 2 else parts[i + 1]
                break
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def idle_duration(self) -> timedelta:
        """Compute idle duration based on status."""
        match self.status:
            case "working":
                return timedelta(0)
            case "idle":
                return datetime.now(tz=timezone.utc) - self.last_activity
            case "offline":
                if self.ended_at:
                    return self.ended_at - self.last_activity
                return timedelta(0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def session_duration(self) -> timedelta:
        """Compute total session duration."""
        if self.status == "offline" and self.ended_at:
            return self.ended_at - self.started_at
        return datetime.now(tz=timezone.utc) - self.started_at
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: All 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cctop/models.py tests/test_models.py
git commit -m "feat: add Session and Event pydantic models"
```

---

### Task 4: Session Discovery Source

**Files:**
- Create: `src/cctop/sources/__init__.py`
- Create: `src/cctop/sources/sessions.py`
- Create: `tests/test_sources_sessions.py`

- [ ] **Step 1: Write failing tests**

`tests/test_sources_sessions.py`:
```python
import json
import os
from pathlib import Path

from cctop.sources.sessions import RawSession, discover_sessions, is_pid_alive


def test_discover_sessions_reads_json_files(tmp_path: Path) -> None:
    session_data = {"pid": os.getpid(), "sessionId": "abc-123", "cwd": "/tmp/test", "startedAt": 1000}
    (tmp_path / f"{os.getpid()}.json").write_text(json.dumps(session_data))

    result = discover_sessions(tmp_path)
    assert len(result) == 1
    assert result[0].session_id == "abc-123"
    assert result[0].pid == os.getpid()
    assert result[0].cwd == Path("/tmp/test")


def test_discover_sessions_skips_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "99999.json").write_text("not json")
    result = discover_sessions(tmp_path)
    assert len(result) == 0


def test_discover_sessions_empty_dir(tmp_path: Path) -> None:
    result = discover_sessions(tmp_path)
    assert len(result) == 0


def test_discover_sessions_nonexistent_dir(tmp_path: Path) -> None:
    result = discover_sessions(tmp_path / "nonexistent")
    assert len(result) == 0


def test_is_pid_alive_current_process() -> None:
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_dead_process() -> None:
    assert is_pid_alive(99999999) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement session discovery**

`src/cctop/sources/__init__.py`:
```python
```

`src/cctop/sources/sessions.py`:
```python
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from pydantic import BaseModel


class RawSession(BaseModel):
    """Raw session data from ~/.claude/sessions/{pid}.json."""

    pid: int
    session_id: str
    cwd: Path
    started_at: datetime

    @property
    def is_alive(self) -> bool:
        return is_pid_alive(self.pid)


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it
    return True


def discover_sessions(sessions_dir: Path) -> list[RawSession]:
    """Read all session files from ~/.claude/sessions/ and return parsed sessions."""
    if not sessions_dir.is_dir():
        return []

    sessions: list[RawSession] = []
    for path in sessions_dir.glob("*.json"):
        try:
            first_line = path.read_text().split("\n", 1)[0]
            data = json.loads(first_line)
            sessions.append(
                RawSession(
                    pid=data["pid"],
                    session_id=data["sessionId"],
                    cwd=Path(data["cwd"]),
                    started_at=datetime.fromtimestamp(data["startedAt"] / 1000, tz=timezone.utc),
                )
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Skipping invalid session file {}: {}", path.name, e)

    return sessions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_sessions.py -v`
Expected: All 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cctop/sources/ tests/test_sources_sessions.py
git commit -m "feat: add session discovery from ~/.claude/sessions/"
```

---

### Task 5: Sessions Index Source

**Files:**
- Create: `src/cctop/sources/index.py`
- Create: `tests/test_sources_index.py`

- [ ] **Step 1: Write failing tests**

`tests/test_sources_index.py`:
```python
import json
from pathlib import Path

from cctop.sources.index import IndexEntry, encode_cwd, find_index_entry


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_index.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement sessions index reader**

`src/cctop/sources/index.py`:
```python
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
    """Look up a session's metadata in the sessions-index.json for its project directory."""
    encoded = encode_cwd(cwd)
    index_path = projects_dir / encoded / "sessions-index.json"

    if not index_path.is_file():
        return None

    try:
        data = json.loads(index_path.read_text())
        for entry_data in data.get("entries", []):
            if entry_data.get("sessionId") == session_id:
                return IndexEntry.model_validate(entry_data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to read sessions-index.json at {}: {}", index_path, e)

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_index.py -v`
Expected: All 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cctop/sources/index.py tests/test_sources_index.py
git commit -m "feat: add sessions-index.json reader"
```

---

### Task 6: Events Tailer Source

**Files:**
- Create: `src/cctop/sources/events.py`
- Create: `tests/test_sources_events.py`

- [ ] **Step 1: Write failing tests**

`tests/test_sources_events.py`:
```python
import json
from pathlib import Path

from cctop.sources.events import EventsTailer


def test_tailer_reads_new_events(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text("")

    tailer = EventsTailer(events_file)

    # Append events
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
    events_file.write_text(
        json.dumps({"ts": 1000, "sid": "abc", "type": "stop"}) + "\n"
    )

    tailer = EventsTailer(events_file)
    events = tailer.read_new()
    assert len(events) == 1

    # No new data — should return empty
    events = tailer.read_new()
    assert len(events) == 0

    # Append more
    with events_file.open("a") as f:
        f.write(json.dumps({"ts": 2000, "sid": "abc", "type": "tool_start", "tool": "Read", "cwd": "/tmp"}) + "\n")

    events = tailer.read_new()
    assert len(events) == 1
    assert events[0].tool == "Read"


def test_tailer_skips_malformed_lines(tmp_path: Path) -> None:
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        "not json\n"
        + json.dumps({"ts": 1000, "sid": "abc", "type": "stop"}) + "\n"
        + '{"ts": 2000, "sid": "abc", "type": "bad_type"}\n'
    )

    tailer = EventsTailer(events_file)
    events = tailer.read_new()
    # Only the valid stop event
    assert len(events) == 1
    assert events[0].type == "stop"


def test_tailer_nonexistent_file(tmp_path: Path) -> None:
    tailer = EventsTailer(tmp_path / "nonexistent.jsonl")
    events = tailer.read_new()
    assert len(events) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_events.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement events tailer**

`src/cctop/sources/events.py`:
```python
import json
from pathlib import Path

from loguru import logger

from cctop.models import Event


class EventsTailer:
    """Tails ~/.cctop/data/events.jsonl, tracking byte offset between reads."""

    def __init__(self, events_file: Path) -> None:
        self._path = events_file
        self._offset: int = 0

    def read_new(self) -> list[Event]:
        """Read any new events since the last call."""
        if not self._path.is_file():
            return []

        events: list[Event] = []
        try:
            with self._path.open() as f:
                f.seek(self._offset)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        events.append(Event.model_validate(data))
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning("Skipping malformed event line: {}", e)
                self._offset = f.tell()
        except OSError as e:
            logger.warning("Failed to read events file: {}", e)

        return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_events.py -v`
Expected: All 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cctop/sources/events.py tests/test_sources_events.py
git commit -m "feat: add events.jsonl tailer"
```

---

### Task 7: GitHub PR Lookup Source

**Files:**
- Create: `src/cctop/sources/github.py`
- Create: `tests/test_sources_github.py`

- [ ] **Step 1: Write failing tests**

`tests/test_sources_github.py`:
```python
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from cctop.sources.github import PRInfo, clear_cache, lookup_pr


@pytest.fixture(autouse=True)
def _clear_pr_cache() -> None:
    clear_cache()


@pytest.mark.asyncio
async def test_lookup_pr_success() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (json.dumps([{"url": "https://github.com/org/repo/pull/42", "title": "Fix bug"}]).encode(), b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await lookup_pr("feat/fix-bug", "/tmp")

    assert result is not None
    assert result.url == "https://github.com/org/repo/pull/42"
    assert result.title == "Fix bug"


@pytest.mark.asyncio
async def test_lookup_pr_no_prs() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"[]", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await lookup_pr("no-pr-branch", "/tmp")

    assert result is None


@pytest.mark.asyncio
async def test_lookup_pr_gh_not_found() -> None:
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await lookup_pr("any-branch", "/tmp")

    assert result is None


@pytest.mark.asyncio
async def test_lookup_pr_cache_hit() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (json.dumps([{"url": "https://example.com/pr/1", "title": "PR"}]).encode(), b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await lookup_pr("cached-branch", "/tmp")
        await lookup_pr("cached-branch", "/tmp")

    # Should only call gh once due to caching
    assert mock_exec.call_count == 1


@pytest.mark.asyncio
async def test_lookup_pr_gh_error_returns_none() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"error")
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await lookup_pr("error-branch", "/tmp")

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_github.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GitHub PR lookup**

`src/cctop/sources/github.py`:
```python
import asyncio
import json

from loguru import logger
from pydantic import BaseModel


class PRInfo(BaseModel):
    """GitHub PR info for a branch."""

    url: str
    title: str


_cache: dict[str, PRInfo | None] = {}


async def lookup_pr(branch: str, cwd: str) -> PRInfo | None:
    """Look up a PR for a git branch using `gh`. Results are cached."""
    if branch in _cache:
        return _cache[branch]

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "list", "--head", branch, "--json", "url,title", "--limit", "1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode != 0:
            _cache[branch] = None
            return None

        prs = json.loads(stdout.decode())
        if prs:
            info = PRInfo(url=prs[0]["url"], title=prs[0]["title"])
            _cache[branch] = info
            return info

        _cache[branch] = None
    except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError, KeyError) as e:
        logger.debug("PR lookup failed for branch {}: {}", branch, e)
        _cache[branch] = None

    return None


def clear_cache() -> None:
    """Clear the PR cache."""
    _cache.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_github.py -v`
Expected: All 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cctop/sources/github.py tests/test_sources_github.py
git commit -m "feat: add async GitHub PR lookup with caching"
```

---

### Task 8: Source Merger

**Files:**
- Create: `src/cctop/sources/merger.py`
- Create: `tests/test_sources_merger.py`

- [ ] **Step 1: Write failing tests**

`tests/test_sources_merger.py`:
```python
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cctop.models import Event
from cctop.sources.merger import SessionManager


def _write_session_file(sessions_dir: Path, pid: int, session_id: str, cwd: str) -> None:
    data = {"pid": pid, "sessionId": session_id, "cwd": cwd, "startedAt": 1773764468081}
    (sessions_dir / f"{pid}.json").write_text(json.dumps(data))


def test_merge_discovers_sessions(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    assert len(mgr.sessions) == 1
    assert mgr.sessions[0].session_id == "abc-123"
    assert mgr.sessions[0].status == "idle"  # No events, alive PID -> idle


def test_merge_marks_dead_pid_offline(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, 99999999, "dead-session", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    assert len(mgr.sessions) == 1
    assert mgr.sessions[0].status == "offline"


def test_merge_applies_tool_events(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    # Apply a tool_start event
    mgr.apply_events([
        Event(ts=1000, sid="abc-123", type="tool_start", tool="Bash", cwd="/tmp/test"),
    ])

    assert mgr.sessions[0].status == "working"
    assert mgr.sessions[0].current_tool == "Bash"


def test_merge_recent_zero_evicts_offline(tmp_path: Path) -> None:
    """With --recent 0 (default), dead PID sessions should not appear."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, 99999999, "dead-session", "/tmp/test")

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
        recent=timedelta(0),  # live sessions only
    )
    mgr.refresh()

    # Offline session should be evicted with recent=0
    assert len(mgr.sessions) == 0


def test_merge_enriches_from_index(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    # Create sessions-index.json
    index_dir = projects_dir / "-tmp-test"
    index_dir.mkdir()
    index_data = {
        "version": 1,
        "originalPath": "/tmp/test",
        "entries": [
            {
                "sessionId": "abc-123",
                "summary": "Working on tests",
                "firstPrompt": "write tests",
                "gitBranch": "feat/tests",
                "messageCount": 10,
                "created": "2026-01-01T00:00:00.000Z",
                "modified": "2026-01-01T01:00:00.000Z",
                "projectPath": "/tmp/test",
                "isSidechain": False,
            }
        ],
    }
    (index_dir / "sessions-index.json").write_text(json.dumps(index_data))

    mgr = SessionManager(
        sessions_dir=sessions_dir,
        projects_dir=projects_dir,
    )
    mgr.refresh()

    assert mgr.sessions[0].summary == "Working on tests"
    assert mgr.sessions[0].git_branch == "feat/tests"
    assert mgr.sessions[0].message_count == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_merger.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement source merger**

`src/cctop/sources/merger.py`:
```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from cctop.models import Event, Session
from cctop.sources.index import find_index_entry
from cctop.sources.sessions import discover_sessions


class SessionManager:
    """Merges all data sources into a list of Session objects."""

    def __init__(
        self,
        sessions_dir: Path | None = None,
        projects_dir: Path | None = None,
        recent: timedelta = timedelta(0),
    ) -> None:
        self._sessions_dir = sessions_dir or Path.home() / ".claude" / "sessions"
        self._projects_dir = projects_dir or Path.home() / ".claude" / "projects"
        self._recent = recent
        self._sessions: dict[str, Session] = {}

    @property
    def sessions(self) -> list[Session]:
        """Return sessions sorted by status (working first, then idle, then offline)."""
        return list(self._sessions.values())

    def refresh(self) -> None:
        """Re-discover sessions and enrich with index data."""
        raw_sessions = discover_sessions(self._sessions_dir)
        now = datetime.now(tz=timezone.utc)

        seen_ids: set[str] = set()
        for raw in raw_sessions:
            seen_ids.add(raw.session_id)
            existing = self._sessions.get(raw.session_id)

            if raw.is_alive:
                status = existing.status if existing and existing.status == "working" else "idle"
                current_tool = existing.current_tool if existing and status == "working" else None
                last_activity = existing.last_activity if existing else raw.started_at

                session = Session(
                    session_id=raw.session_id,
                    pid=raw.pid,
                    cwd=raw.cwd,
                    project_name=raw.cwd.name or str(raw.cwd),
                    status=status,
                    current_tool=current_tool,
                    started_at=raw.started_at,
                    last_activity=last_activity,
                )
            else:
                ended_at = existing.ended_at if existing else now
                last_activity = existing.last_activity if existing else raw.started_at

                session = Session(
                    session_id=raw.session_id,
                    pid=raw.pid,
                    cwd=raw.cwd,
                    project_name=raw.cwd.name or str(raw.cwd),
                    status="offline",
                    started_at=raw.started_at,
                    last_activity=last_activity,
                    ended_at=ended_at,
                )

            # Evict offline sessions when recent=0 (live only)
            if session.status == "offline" and self._recent == timedelta(0):
                self._sessions.pop(raw.session_id, None)
                continue

            # Enrich from sessions-index.json
            entry = find_index_entry(self._projects_dir, raw.cwd, raw.session_id)
            if entry:
                session.summary = entry.summary
                session.first_prompt = entry.first_prompt
                session.git_branch = entry.git_branch
                session.message_count = entry.message_count

            self._sessions[raw.session_id] = session

        # Remove sessions that are no longer in the files and past the recent window
        for sid in list(self._sessions.keys()):
            if sid not in seen_ids:
                session = self._sessions[sid]
                if session.status != "offline":
                    session.status = "offline"
                    session.ended_at = now
                    self._sessions[sid] = session

                if self._recent == timedelta(0):
                    del self._sessions[sid]
                elif session.ended_at and (now - session.ended_at) > self._recent:
                    del self._sessions[sid]

    def apply_events(self, events: list[Event]) -> None:
        """Apply hook events to update session status."""
        for event in events:
            session = self._sessions.get(event.sid)
            if session is None:
                continue

            now_ts = datetime.fromtimestamp(event.ts / 1000, tz=timezone.utc)

            match event.type:
                case "tool_start":
                    session.status = "working"
                    session.current_tool = event.tool
                    session.last_activity = now_ts
                case "tool_end" | "stop":
                    session.status = "idle"
                    session.current_tool = None
                    session.last_activity = now_ts
                case "session_end":
                    session.status = "offline"
                    session.ended_at = now_ts
                    session.last_activity = now_ts
                case "session_start":
                    session.last_activity = now_ts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_merger.py -v`
Expected: All 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cctop/sources/merger.py tests/test_sources_merger.py
git commit -m "feat: add source merger that combines all data sources"
```

---

### Task 9: Hook Script + Install/Uninstall

**Files:**
- Create: `src/cctop/hooks/__init__.py`
- Create: `src/cctop/hooks/install.py`
- Create: `src/cctop/hooks/cctop-hook.sh`
- Create: `tests/test_hooks_install.py`

- [ ] **Step 1: Write the hook bash script**

`src/cctop/hooks/cctop-hook.sh`:
```bash
#!/bin/bash
# cctop hook — Captures Claude Code events for TUI monitoring
# Installed by: cctop install
set -e

KNOWN_PATHS=("/opt/homebrew/bin" "/usr/local/bin" "$HOME/.local/bin" "/usr/bin" "/bin")
for dir in "${KNOWN_PATHS[@]}"; do
  [ -d "$dir" ] && export PATH="$dir:$PATH"
done

JQ=$(command -v jq 2>/dev/null) || exit 0

CCTOP_DATA_DIR="${CCTOP_DATA_DIR:-$HOME/.cctop/data}"
EVENTS_FILE="$CCTOP_DATA_DIR/events.jsonl"
mkdir -p "$CCTOP_DATA_DIR"

input=$(cat)

hook_event_name=$(echo "$input" | "$JQ" -r '.hook_event_name // "unknown"')
session_id=$(echo "$input" | "$JQ" -r '.session_id // "unknown"')
cwd=$(echo "$input" | "$JQ" -r '.cwd // ""')

# Timestamp in milliseconds
if command -v perl &> /dev/null; then
  timestamp=$(perl -MTime::HiRes=time -e 'printf "%.0f", time * 1000')
elif command -v python3 &> /dev/null; then
  timestamp=$(python3 -c 'import time; print(int(time.time() * 1000))')
else
  timestamp=$(($(date +%s) * 1000))
fi

case "$hook_event_name" in
  PreToolUse)
    tool_name=$(echo "$input" | "$JQ" -r '.tool_name // "unknown"')
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"tool_start\",\"tool\":\"$tool_name\",\"cwd\":\"$cwd\"}" >> "$EVENTS_FILE"
    ;;
  PostToolUse)
    tool_name=$(echo "$input" | "$JQ" -r '.tool_name // "unknown"')
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"tool_end\",\"tool\":\"$tool_name\"}" >> "$EVENTS_FILE"
    ;;
  Stop)
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"stop\"}" >> "$EVENTS_FILE"
    ;;
  SessionStart)
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"session_start\",\"cwd\":\"$cwd\"}" >> "$EVENTS_FILE"
    ;;
  SessionEnd)
    echo "{\"ts\":$timestamp,\"sid\":\"$session_id\",\"type\":\"session_end\"}" >> "$EVENTS_FILE"
    ;;
esac

exit 0
```

- [ ] **Step 2: Write failing tests for install/uninstall**

`tests/test_hooks_install.py`:
```python
import json
from pathlib import Path
from unittest.mock import patch

from cctop.hooks.install import install_hooks, uninstall_hooks


def test_install_creates_directories(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    claude_settings.write_text("{}")

    with patch("shutil.which", return_value="/usr/bin/jq"):
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    assert (cctop_dir / "hooks" / "cctop-hook.sh").is_file()
    assert (cctop_dir / "data").is_dir()


def test_install_appends_hooks_to_settings(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    claude_settings.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "other-hook.sh"}]}]}}))

    with patch("shutil.which", return_value="/usr/bin/jq"):
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    data = json.loads(claude_settings.read_text())
    # Should have both the existing hook and the cctop hook
    pre_tool_hooks = data["hooks"]["PreToolUse"]
    assert len(pre_tool_hooks) == 2
    assert "other-hook.sh" in pre_tool_hooks[0]["hooks"][0]["command"]
    assert "cctop" in pre_tool_hooks[1]["hooks"][0]["command"]


def test_install_does_not_duplicate_hooks(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    claude_settings.write_text("{}")

    with patch("shutil.which", return_value="/usr/bin/jq"):
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    data = json.loads(claude_settings.read_text())
    assert len(data["hooks"]["PreToolUse"]) == 1


def test_uninstall_removes_only_cctop_hooks(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    settings_data = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "other-hook.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": str(cctop_dir / "hooks" / "cctop-hook.sh")}]},
            ]
        }
    }
    claude_settings.write_text(json.dumps(settings_data))
    cctop_dir.mkdir(parents=True)

    uninstall_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    data = json.loads(claude_settings.read_text())
    assert len(data["hooks"]["PreToolUse"]) == 1
    assert "other-hook.sh" in data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert not cctop_dir.exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_install.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement install/uninstall**

`src/cctop/hooks/__init__.py`:
```python
```

`src/cctop/hooks/install.py`:
```python
import json
import os
import shutil
import tempfile
from importlib import resources
from pathlib import Path

from loguru import logger

HOOK_EVENTS = ["PreToolUse", "PostToolUse", "Stop", "SessionStart", "SessionEnd"]
# Events that use a tool matcher
MATCHER_EVENTS = {"PreToolUse", "PostToolUse"}


def install_hooks(
    cctop_dir: Path | None = None,
    settings_path: Path | None = None,
) -> None:
    """Install cctop hooks into Claude Code settings."""
    cctop_dir = cctop_dir or Path.home() / ".cctop"
    settings_path = settings_path or Path.home() / ".claude" / "settings.json"

    # Check for jq
    if not shutil.which("jq"):
        raise RuntimeError("jq is required for hooks. Install it with: brew install jq")

    # Create directories
    hooks_dir = cctop_dir / "hooks"
    data_dir = cctop_dir / "data"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Copy hook script
    hook_dest = hooks_dir / "cctop-hook.sh"
    hook_source = resources.files("cctop.hooks").joinpath("cctop-hook.sh")
    hook_dest.write_bytes(hook_source.read_bytes())
    hook_dest.chmod(0o755)

    # Read existing settings
    if settings_path.is_file():
        settings = json.loads(settings_path.read_text())
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    hook_command = str(hook_dest)

    # Add hooks for each event (append, never replace)
    for event in HOOK_EVENTS:
        event_hooks = hooks.setdefault(event, [])

        # Check if cctop hook already exists
        already_installed = any(
            "cctop" in h.get("hooks", [{}])[0].get("command", "")
            for h in event_hooks
            if isinstance(h, dict)
        )
        if already_installed:
            continue

        entry: dict = {
            "hooks": [{"type": "command", "command": hook_command, "timeout": 5}],
        }
        if event in MATCHER_EVENTS:
            entry["matcher"] = "*"

        event_hooks.append(entry)

    # Atomic write
    _atomic_write_json(settings_path, settings)
    logger.info("Hooks installed. Restart your Claude Code sessions for hooks to take effect.")


def uninstall_hooks(
    cctop_dir: Path | None = None,
    settings_path: Path | None = None,
) -> None:
    """Remove cctop hooks from Claude Code settings and clean up."""
    cctop_dir = cctop_dir or Path.home() / ".cctop"
    settings_path = settings_path or Path.home() / ".claude" / "settings.json"

    # Remove hooks from settings
    if settings_path.is_file():
        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {})

        for event in HOOK_EVENTS:
            if event in hooks:
                hooks[event] = [
                    h for h in hooks[event]
                    if not any("cctop" in cmd.get("command", "") for cmd in h.get("hooks", []))
                ]
                if not hooks[event]:
                    del hooks[event]

        _atomic_write_json(settings_path, settings)

    # Remove cctop directory
    if cctop_dir.exists():
        shutil.rmtree(cctop_dir)

    logger.info("cctop hooks removed and data cleaned up.")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON to a file atomically using temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.rename(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_install.py -v`
Expected: All 4 PASS.

- [ ] **Step 6: Wire install/uninstall into CLI**

Update `src/cctop/cli.py` to call the real install/uninstall functions:
```python
import typer

from cctop.hooks.install import install_hooks, uninstall_hooks

app = typer.Typer(help="cctop — monitor Claude Code sessions in real-time")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    recent: str = typer.Option("0", help="Include sessions ended within this duration (e.g. 30m, 1h, 2h, 1d)"),
) -> None:
    """Launch the cctop TUI."""
    if ctx.invoked_subcommand is None:
        typer.echo(f"cctop TUI would launch here (recent={recent})")


@app.command()
def install() -> None:
    """Install cctop hooks into Claude Code settings."""
    try:
        install_hooks()
        typer.echo("Hooks installed. Restart your Claude Code sessions for hooks to take effect.")
    except RuntimeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@app.command()
def uninstall() -> None:
    """Remove cctop hooks and clean up."""
    uninstall_hooks()
    typer.echo("cctop hooks removed and data cleaned up.")
```

- [ ] **Step 7: Commit**

```bash
git add src/cctop/hooks/ src/cctop/cli.py tests/test_hooks_install.py
git commit -m "feat: add hook script and install/uninstall commands"
```

---

### Task 10: Textual App — Session List Widget

**Files:**
- Create: `src/cctop/widgets/__init__.py`
- Create: `src/cctop/widgets/session_row.py`
- Create: `src/cctop/widgets/session_detail.py`
- Create: `src/cctop/widgets/session_list.py`

- [ ] **Step 1: Create session row widget**

`src/cctop/widgets/__init__.py`:
```python
```

`src/cctop/widgets/session_row.py`:
```python
from datetime import timedelta

from rich.text import Text
from textual.widgets import Static

from cctop.models import Session

STATUS_ICONS = {
    "working": ("●", "green"),
    "idle": ("○", "yellow"),
    "offline": ("◌", "bright_black"),
}


def format_duration(td: timedelta) -> str:
    """Format a timedelta into a human-readable short string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "0s"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


class SessionRow(Static):
    """A single collapsed session row."""

    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render(self) -> Text:
        s = self.session
        icon, color = STATUS_ICONS.get(s.status, ("?", "white"))

        line = Text()
        line.append(f" {icon} ", style=color)
        line.append(f"{s.project_name:<24}", style="bold")

        branch_display = s.worktree_name or s.git_branch or "—"
        line.append(f"{branch_display:<16}", style="cyan")

        if s.status == "working" and s.current_tool:
            line.append(f"Working: {s.current_tool:<10}", style="green")
        elif s.status == "idle":
            line.append(f"{'Idle':<20}", style="yellow")
        else:
            line.append(f"{'Offline':<20}", style="bright_black")

        line.append(f"{format_duration(s.session_duration):>8}", style="white")
        line.append("  ", style="white")

        if s.status == "offline":
            line.append(f"{'—':>6}", style="bright_black")
        else:
            line.append(f"{format_duration(s.idle_duration):>6}", style="white")

        return line
```

- [ ] **Step 2: Create session detail widget**

`src/cctop/widgets/session_detail.py`:
```python
from rich.text import Text
from textual.widgets import Static

from cctop.models import Session


class SessionDetail(Static):
    """Expanded detail view for a session."""

    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render(self) -> Text:
        s = self.session
        lines = Text()

        if s.pr_url and s.pr_title:
            lines.append(f"  │  PR: {s.pr_title}\n", style="blue")
            lines.append(f"  │  {s.pr_url}\n", style="dim blue")

        if s.summary:
            lines.append(f"  │  Summary: {s.summary}\n", style="white")

        if s.first_prompt:
            prompt = s.first_prompt[:120] + "..." if len(s.first_prompt) > 120 else s.first_prompt
            lines.append(f"  │  Prompt: {prompt}\n", style="dim")

        lines.append(f"  │  Dir: {s.cwd}\n", style="dim")

        if s.git_branch:
            lines.append(f"  │  Branch: {s.git_branch}", style="cyan")
            if s.message_count:
                lines.append(f"  Messages: {s.message_count}", style="dim")
            lines.append("\n")

        return lines
```

- [ ] **Step 3: Create session list widget**

`src/cctop/widgets/session_list.py`:
```python
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from cctop.models import Session
from cctop.widgets.session_detail import SessionDetail
from cctop.widgets.session_row import SessionRow


class SessionList(VerticalScroll):
    """Scrollable list of sessions with expand/collapse."""

    BINDINGS = [
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("enter", "toggle_expand", "Expand/Collapse"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: list[Session] = []
        self._cursor: int = 0
        self._expanded: set[str] = set()

    def update_sessions(self, sessions: list[Session]) -> None:
        """Update the session list and re-render."""
        self._sessions = sessions
        if self._cursor >= len(sessions):
            self._cursor = max(0, len(sessions) - 1)
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild the widget tree."""
        self.remove_children()
        for i, session in enumerate(self._sessions):
            row = SessionRow(session, classes="cursor" if i == self._cursor else "")
            self.mount(row)
            if session.session_id in self._expanded:
                self.mount(SessionDetail(session))

    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._rebuild()

    def action_cursor_down(self) -> None:
        if self._cursor < len(self._sessions) - 1:
            self._cursor += 1
            self._rebuild()

    def action_toggle_expand(self) -> None:
        if not self._sessions:
            return
        sid = self._sessions[self._cursor].session_id
        if sid in self._expanded:
            self._expanded.discard(sid)
        else:
            self._expanded.add(sid)
        self._rebuild()
```

- [ ] **Step 4: Commit**

```bash
git add src/cctop/widgets/
git commit -m "feat: add session list, row, and detail Textual widgets"
```

---

### Task 11: Textual App — Header, Footer, and Main App

**Files:**
- Create: `src/cctop/widgets/header.py`
- Create: `src/cctop/widgets/footer.py`
- Create: `src/cctop/app.py`

- [ ] **Step 1: Create header widget**

`src/cctop/widgets/header.py`:
```python
from rich.text import Text
from textual.widgets import Static

from cctop.models import Session

SORT_LABELS = ["idle time", "duration", "name", "status"]


class Header(Static):
    """Top bar showing session counts and current sort mode."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: list[Session] = []
        self._sort_index: int = 0

    def update_info(self, sessions: list[Session], sort_index: int) -> None:
        self._sessions = sessions
        self._sort_index = sort_index
        self.refresh()

    def render(self) -> Text:
        total = len(self._sessions)
        working = sum(1 for s in self._sessions if s.status == "working")
        idle = sum(1 for s in self._sessions if s.status == "idle")
        offline = sum(1 for s in self._sessions if s.status == "offline")

        line = Text()
        line.append("  cctop", style="bold white")
        line.append(f" — {total} session{'s' if total != 1 else ''}", style="white")
        line.append(" (", style="dim")
        if working:
            line.append(f"{working} working", style="green")
            if idle or offline:
                line.append(", ", style="dim")
        if idle:
            line.append(f"{idle} idle", style="yellow")
            if offline:
                line.append(", ", style="dim")
        if offline:
            line.append(f"{offline} offline", style="bright_black")
        line.append(")", style="dim")

        sort_label = SORT_LABELS[self._sort_index % len(SORT_LABELS)]
        padding = " " * max(1, 60 - len(line.plain))
        line.append(padding)
        line.append(f"Sort: [{sort_label} ▼]", style="dim")

        return line
```

- [ ] **Step 2: Create footer widget**

`src/cctop/widgets/footer.py`:
```python
from rich.text import Text
from textual.widgets import Static


class Footer(Static):
    """Bottom bar showing keyboard shortcuts."""

    def render(self) -> Text:
        line = Text()
        shortcuts = [
            ("↑↓", "navigate"),
            ("Enter", "expand/collapse"),
            ("F6", "sort"),
            ("/", "filter"),
            ("?", "help"),
            ("q", "quit"),
        ]
        for key, action in shortcuts:
            line.append(f"  {key} ", style="bold")
            line.append(action, style="dim")
        return line
```

- [ ] **Step 3: Create main Textual app**

`src/cctop/app.py`:
```python
from datetime import timedelta
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches

from cctop.models import Session
from cctop.sources.events import EventsTailer
from cctop.sources.merger import SessionManager
from cctop.widgets.footer import Footer
from cctop.widgets.header import Header
from cctop.widgets.session_list import SessionList

SORT_KEYS: list[tuple[str, bool]] = [
    ("idle_duration", True),   # longest idle first
    ("session_duration", True),  # longest duration first
    ("project_name", False),   # alphabetical
    ("status", False),         # working -> idle -> offline
]

STATUS_ORDER = {"working": 0, "idle": 1, "offline": 2}


class CctopApp(App):
    """Main cctop Textual application."""

    TITLE = "cctop"
    CSS = """
    Header {
        height: 1;
        background: $surface;
    }
    Footer {
        height: 1;
        background: $surface;
        dock: bottom;
    }
    SessionList {
        height: 1fr;
    }
    .cursor {
        background: $accent 30%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f10", "quit", "Quit", show=False),
        Binding("f6", "cycle_sort", "Sort"),
        Binding("greater_than", "cycle_sort", "Sort", show=False),
        Binding("less_than", "cycle_sort_reverse", "Sort reverse", show=False),
        Binding("slash", "toggle_filter", "Filter"),
        Binding("question_mark", "show_help", "Help"),
        Binding("h", "show_help", "Help", show=False),
    ]

    def __init__(self, recent: timedelta = timedelta(0), **kwargs) -> None:
        super().__init__(**kwargs)
        self._manager = SessionManager(recent=recent)
        self._tailer = EventsTailer(Path.home() / ".cctop" / "data" / "events.jsonl")
        self._sort_index = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield SessionList()
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2, self._poll_fast)
        self.set_interval(10, self._poll_slow)
        self._poll_fast()
        self._poll_slow()

    def _poll_fast(self) -> None:
        """Fast polling: session discovery, PID liveness, events."""
        self._manager.refresh()
        events = self._tailer.read_new()
        if events:
            self._manager.apply_events(events)
        self._update_ui()

    async def _poll_slow(self) -> None:
        """Slow polling: sessions-index refresh, PR lookups."""
        # Index data is refreshed in manager.refresh() already
        # PR lookups for sessions with a branch but no cached PR
        from cctop.sources.github import lookup_pr

        for session in self._manager.sessions:
            if session.git_branch and not session.pr_url:
                info = await lookup_pr(session.git_branch, str(session.cwd))
                if info:
                    session.pr_url = info.url
                    session.pr_title = info.title
        self._update_ui()

    def _sort_sessions(self, sessions: list[Session]) -> list[Session]:
        key_name, reverse = SORT_KEYS[self._sort_index % len(SORT_KEYS)]
        if key_name == "status":
            return sorted(sessions, key=lambda s: STATUS_ORDER.get(s.status, 9), reverse=reverse)
        return sorted(sessions, key=lambda s: getattr(s, key_name), reverse=reverse)

    def _update_ui(self) -> None:
        sessions = self._sort_sessions(self._manager.sessions)
        try:
            self.query_one(Header).update_info(sessions, self._sort_index)
            self.query_one(SessionList).update_sessions(sessions)
        except NoMatches:
            pass

    def action_cycle_sort(self) -> None:
        self._sort_index = (self._sort_index + 1) % len(SORT_KEYS)
        self._update_ui()

    def action_cycle_sort_reverse(self) -> None:
        self._sort_index = (self._sort_index - 1) % len(SORT_KEYS)
        self._update_ui()

    def action_toggle_filter(self) -> None:
        """Toggle filter input. Simple substring filter on project name."""
        self.notify("Filter: not yet implemented (planned for v0.2)", severity="information", timeout=3)

    def action_show_help(self) -> None:
        """Show help screen with keybindings."""
        help_text = (
            "cctop — Claude Code session monitor\n\n"
            "↑/↓ or k/j   Navigate sessions\n"
            "Enter         Expand / collapse\n"
            "F6 or >/<     Cycle sort mode\n"
            "/             Filter (coming soon)\n"
            "?/h           This help\n"
            "q / F10       Quit"
        )
        self.notify(help_text, severity="information", timeout=15)
```

- [ ] **Step 4: Wire app into CLI**

Update `src/cctop/cli.py` — replace the placeholder in `main()`:
```python
import typer

from cctop.duration import parse_duration
from cctop.hooks.install import install_hooks, uninstall_hooks

app = typer.Typer(help="cctop — monitor Claude Code sessions in real-time")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    recent: str = typer.Option("0", help="Include sessions ended within this duration (e.g. 30m, 1h, 2h, 1d)"),
) -> None:
    """Launch the cctop TUI."""
    if ctx.invoked_subcommand is None:
        from cctop.app import CctopApp

        recent_td = parse_duration(recent)
        cctop_app = CctopApp(recent=recent_td)
        cctop_app.run()


@app.command()
def install() -> None:
    """Install cctop hooks into Claude Code settings."""
    try:
        install_hooks()
        typer.echo("Hooks installed. Restart your Claude Code sessions for hooks to take effect.")
    except RuntimeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1)


@app.command()
def uninstall() -> None:
    """Remove cctop hooks and clean up."""
    uninstall_hooks()
    typer.echo("cctop hooks removed and data cleaned up.")
```

- [ ] **Step 5: Manual smoke test**

Run: `uv run cctop`
Expected: TUI launches, shows any active Claude sessions. Press `q` to quit.

- [ ] **Step 6: Commit**

```bash
git add src/cctop/app.py src/cctop/cli.py src/cctop/widgets/header.py src/cctop/widgets/footer.py
git commit -m "feat: add Textual app with header, footer, session list, and polling loop"
```

---

### Task 12: Integration Test

**Files:**
- Create: `tests/test_app.py`

- [ ] **Step 1: Write Textual app pilot test**

`tests/test_app.py`:
```python
import json
import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.pilot import Pilot

from cctop.app import CctopApp


@pytest.fixture
def mock_sessions(tmp_path: Path) -> tuple[Path, Path]:
    """Create mock Claude session files."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Create a session file with current PID (so it appears alive)
    data = {"pid": os.getpid(), "sessionId": "test-session-1", "cwd": str(tmp_path), "startedAt": 1773764468081}
    (sessions_dir / f"{os.getpid()}.json").write_text(json.dumps(data))

    return sessions_dir, projects_dir


@pytest.mark.asyncio
async def test_app_launches_and_quits(mock_sessions: tuple[Path, Path]) -> None:
    sessions_dir, projects_dir = mock_sessions

    app = CctopApp(recent=timedelta(0))
    app._manager._sessions_dir = sessions_dir
    app._manager._projects_dir = projects_dir

    async with app.run_test() as pilot:
        # App should have mounted
        assert app.is_running
        # Quit
        await pilot.press("q")


@pytest.mark.asyncio
async def test_app_shows_sessions(mock_sessions: tuple[Path, Path]) -> None:
    sessions_dir, projects_dir = mock_sessions

    app = CctopApp(recent=timedelta(0))
    app._manager._sessions_dir = sessions_dir
    app._manager._projects_dir = projects_dir

    async with app.run_test(size=(120, 30)) as pilot:
        # Wait for first poll
        await pilot.pause()
        # Check that the app rendered something
        assert len(app._manager.sessions) == 1
        await pilot.press("q")
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_app.py -v`
Expected: All PASS.

- [ ] **Step 3: Run full test suite + quality checks**

Run:
```bash
uv run pytest -v
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run pyright src/ tests/
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_app.py
git commit -m "test: add Textual app integration tests"
```

---

### Task 13: Events File Cleanup + Hooks Warning Banner

**Files:**
- Modify: `src/cctop/sources/events.py`
- Modify: `src/cctop/app.py`
- Create: `tests/test_events_cleanup.py`

- [ ] **Step 0: Write tests for events cleanup**

`tests/test_events_cleanup.py`:
```python
import json
import time
from pathlib import Path

from cctop.sources.events import EventsTailer, MAX_EVENTS_FILE_SIZE


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
        line = json.dumps({"ts": now_ms - (25 * 3600 * 1000), "sid": "old", "type": "stop", "padding": "x" * 500}) + "\n"
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
```

- [ ] **Step 1: Add events file cleanup to EventsTailer**

Add a `cleanup` method to `EventsTailer` in `src/cctop/sources/events.py`:

```python
import json
import time
from pathlib import Path

from loguru import logger

from cctop.models import Event

MAX_EVENTS_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_EVENT_AGE_SECONDS = 86400  # 24 hours


class EventsTailer:
    """Tails ~/.cctop/data/events.jsonl, tracking byte offset between reads."""

    def __init__(self, events_file: Path) -> None:
        self._path = events_file
        self._offset: int = 0

    @property
    def hooks_installed(self) -> bool:
        """Check if the events file directory exists (proxy for hooks being installed)."""
        return self._path.parent.is_dir()

    def cleanup_if_needed(self) -> None:
        """Truncate old events if file exceeds size limit."""
        if not self._path.is_file():
            return

        try:
            if self._path.stat().st_size <= MAX_EVENTS_FILE_SIZE:
                return

            cutoff = (time.time() - MAX_EVENT_AGE_SECONDS) * 1000  # ms
            kept_lines: list[str] = []
            with self._path.open() as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("ts", 0) >= cutoff:
                            kept_lines.append(line)
                    except json.JSONDecodeError:
                        pass

            self._path.write_text("".join(kept_lines))
            self._offset = 0
            logger.info("Cleaned up events.jsonl: kept {} recent events", len(kept_lines))
        except OSError as e:
            logger.warning("Failed to clean up events file: {}", e)

    def read_new(self) -> list[Event]:
        """Read any new events since the last call."""
        if not self._path.is_file():
            return []

        events: list[Event] = []
        try:
            with self._path.open() as f:
                f.seek(self._offset)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        events.append(Event.model_validate(data))
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning("Skipping malformed event line: {}", e)
                self._offset = f.tell()
        except OSError as e:
            logger.warning("Failed to read events file: {}", e)

        return events
```

- [ ] **Step 2: Add hooks warning banner to app**

In `src/cctop/app.py`, add a notification on mount if hooks aren't installed:

Add after `self._poll_slow()` in `on_mount`:
```python
if not self._tailer.hooks_installed:
    self.notify(
        "Hooks not installed — run 'cctop install' for real-time status.",
        severity="warning",
        timeout=10,
    )
```

And call cleanup on mount:
```python
self._tailer.cleanup_if_needed()
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/cctop/sources/events.py src/cctop/app.py tests/test_events_cleanup.py
git commit -m "feat: add events file cleanup and hooks warning banner"
```

---

### Task 14: Push to GitHub + Final Validation

- [ ] **Step 1: Run all quality checks**

Run:
```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run pyright src/ tests/
uv run pytest -v
```

Expected: All pass.

- [ ] **Step 2: Push to GitHub**

```bash
cd /Users/yorrickjansen/work/cctop
git push origin main
```

- [ ] **Step 3: Verify README is useful**

Update `README.md` with basic install/usage instructions.

- [ ] **Step 4: Final commit and push**

```bash
git add README.md
git commit -m "docs: add install and usage instructions to README"
git push origin main
```
