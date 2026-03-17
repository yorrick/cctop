# LLM Session Summaries Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate on-demand 1-sentence session summaries via Claude API (claude-haiku-4-5) when a session row is expanded in the cctop TUI.

**Architecture:** A new `summarize.py` module handles transcript stripping and Claude API calls. `SessionList` caches LLM-generated summaries in `_llm_summaries: dict[str, str]` (never overwritten by the merger) and fires background workers via Textual's `run_worker`. `SessionDetail` receives the LLM summary as a separate constructor argument and renders it with priority over the index-derived summary.

**Tech Stack:** `anthropic` SDK (AsyncAnthropic, claude-haiku-4-5), Textual workers, asyncio.wait_for, pytest with unittest.mock.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/cctop/sources/summarize.py` | **Create** | `strip_transcript()` + `generate_summary()` |
| `src/cctop/sources/index.py` | **Modify** | Add `find_transcript_path()` |
| `src/cctop/widgets/session_detail.py` | **Modify** | Accept `llm_summary` arg, render with priority |
| `src/cctop/widgets/session_list.py` | **Modify** | `_llm_summaries` cache, workers, `r` keybinding |
| `src/cctop/app.py` | **Modify** | Pass `projects_dir` to `SessionList` |
| `pyproject.toml` | **Modify** | Add `anthropic` dependency |
| `tests/test_sources_summarize.py` | **Create** | Tests for strip + generate |
| `tests/test_sources_index.py` | **Modify** | Tests for `find_transcript_path` |

---

## Task 1: Add `anthropic` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add anthropic to dependencies**

In `pyproject.toml`, add `"anthropic>=0.40"` to the `dependencies` list:

```toml
dependencies = [
    "textual>=3.0",
    "typer>=0.15",
    "pydantic>=2.0",
    "loguru",
    "anthropic>=0.40",
]
```

- [ ] **Step 2: Sync the environment**

```bash
uv sync
```

Expected: resolves and installs `anthropic` package without errors.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add anthropic SDK dependency"
```

---

## Task 2: Add `find_transcript_path` to `index.py`

**Files:**
- Modify: `src/cctop/sources/index.py`
- Modify: `tests/test_sources_index.py`

This function locates the `.jsonl` transcript file for a session. It first tries the direct path by session ID, then falls back to scanning for recently-modified transcripts (handles resumed sessions where PID-file ID differs from transcript ID).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sources_index.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from cctop.sources.index import find_transcript_path


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
    import os, time
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sources_index.py::test_find_transcript_path_direct_match tests/test_sources_index.py::test_find_transcript_path_fallback_active tests/test_sources_index.py::test_find_transcript_path_no_match -v
```

Expected: FAIL — `ImportError: cannot import name 'find_transcript_path'`

- [ ] **Step 3: Implement `find_transcript_path` in `index.py`**

Add at the end of `src/cctop/sources/index.py` (after the existing functions), adding `datetime` to the imports at the top:

```python
from datetime import datetime
```

Then add the function:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sources_index.py -v
```

Expected: All tests pass including the 3 new ones.

- [ ] **Step 5: Run linting/type checks**

```bash
uv run ruff format src/cctop/sources/index.py && uv run ruff check src/cctop/sources/index.py && uv run pyright src/cctop/sources/index.py
```

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/cctop/sources/index.py tests/test_sources_index.py
git commit -m "feat: add find_transcript_path to index.py"
```

---

## Task 3: Create `summarize.py` — transcript stripping

**Files:**
- Create: `src/cctop/sources/summarize.py`
- Create: `tests/test_sources_summarize.py`

`strip_transcript` is the core utility — it reads a JSONL transcript and produces a compact text representation for the LLM.

- [ ] **Step 1: Write failing tests for `strip_transcript`**

Create `tests/test_sources_summarize.py`:

```python
import json
from pathlib import Path

import pytest

from cctop.sources.summarize import strip_transcript


def _write_transcript(path: Path, messages: list[dict]) -> None:  # type: ignore[type-arg]
    path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")


def test_strip_transcript_basic(tmp_path: Path) -> None:
    """Extracts user and assistant messages, skips system entries."""
    t = tmp_path / "sess.jsonl"
    _write_transcript(t, [
        {"type": "system", "content": "system stuff"},
        {"type": "user", "message": {"content": [{"type": "text", "text": "Hello Claude"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello!"}]}},
        {"type": "progress", "content": "ignored"},
    ])
    result = strip_transcript(t)
    assert "Hello Claude" in result
    assert "Hello!" in result
    assert "system stuff" not in result
    assert "ignored" not in result


def test_strip_transcript_strips_system_tags(tmp_path: Path) -> None:
    """Removes <system-reminder> and similar tags from user messages."""
    t = tmp_path / "sess.jsonl"
    _write_transcript(t, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "<system-reminder>boilerplate</system-reminder>What is 2+2?"}]}},
    ])
    result = strip_transcript(t)
    assert "boilerplate" not in result
    assert "What is 2+2?" in result


def test_strip_transcript_truncates_long_messages(tmp_path: Path) -> None:
    """Truncates individual messages to 500 chars."""
    t = tmp_path / "sess.jsonl"
    long_text = "x" * 1000
    _write_transcript(t, [
        {"type": "user", "message": {"content": [{"type": "text", "text": long_text}]}},
    ])
    result = strip_transcript(t)
    # The user message content should be truncated
    assert len(result) < 600


def test_strip_transcript_first_last_three(tmp_path: Path) -> None:
    """Takes first 3 + last 3, adds omission separator for skipped middle."""
    t = tmp_path / "sess.jsonl"
    messages = []
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({
            "type": role,
            "message": {"content": [{"type": "text", "text": f"message {i}"}]},
        })
    _write_transcript(t, messages)
    result = strip_transcript(t)
    assert "message 0" in result
    assert "message 9" in result
    assert "omitted" in result
    # Middle messages should not appear
    assert "message 4" not in result


def test_strip_transcript_no_separator_when_few_messages(tmp_path: Path) -> None:
    """No separator when total messages <= 6."""
    t = tmp_path / "sess.jsonl"
    messages = [
        {"type": "user", "message": {"content": [{"type": "text", "text": f"msg {i}"}]}}
        for i in range(4)
    ]
    _write_transcript(t, messages)
    result = strip_transcript(t)
    assert "omitted" not in result


def test_strip_transcript_under_3000_chars(tmp_path: Path) -> None:
    """Output stays under 3000 chars even with max content."""
    t = tmp_path / "sess.jsonl"
    messages = []
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({
            "type": role,
            "message": {"content": [{"type": "text", "text": "x" * 1000}]},
        })
    _write_transcript(t, messages)
    result = strip_transcript(t)
    assert len(result) <= 3000


def test_strip_transcript_empty_file(tmp_path: Path) -> None:
    """Returns empty string for empty transcript."""
    t = tmp_path / "sess.jsonl"
    t.write_text("")
    result = strip_transcript(t)
    assert result == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sources_summarize.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cctop.sources.summarize'`

- [ ] **Step 3: Implement `strip_transcript` in `summarize.py`**

Create `src/cctop/sources/summarize.py`:

```python
import asyncio
import json
from pathlib import Path

import anthropic
from loguru import logger

from cctop.sources.index import _SYSTEM_TAG_RE

_MAX_MSG_CHARS = 500
_MAX_TOTAL_CHARS = 3000
_KEEP_FIRST = 3
_KEEP_LAST = 3


def _extract_text(message: dict) -> str | None:  # type: ignore[type-arg]
    """Extract clean text content from a transcript message dict."""
    content = message.get("message", {}).get("content", "")
    if isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                text = _SYSTEM_TAG_RE.sub("", block["text"]).strip()
                if text:
                    return text
    elif isinstance(content, str):
        text = _SYSTEM_TAG_RE.sub("", content).strip()
        if text:
            return text
    return None


def strip_transcript(transcript_path: Path) -> str:
    """Read a JSONL transcript and return a compact text representation.

    Extracts only user/assistant messages, strips system tags, takes first 3
    + last 3 messages, truncates each to 500 chars. Target: under 3000 chars.
    """
    messages: list[tuple[str, str]] = []  # (role, text)

    try:
        with transcript_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type not in ("user", "assistant"):
                    continue

                text = _extract_text(data)
                if text:
                    messages.append((msg_type, text))
    except OSError:
        return ""

    if not messages:
        return ""

    # Select first 3 + last 3, with omission separator if needed
    if len(messages) <= _KEEP_FIRST + _KEEP_LAST:
        selected = messages
        omitted = 0
    else:
        first = messages[:_KEEP_FIRST]
        last = messages[-_KEEP_LAST:]
        omitted = len(messages) - _KEEP_FIRST - _KEEP_LAST
        selected = first + [("", "")] + last  # sentinel for separator

    parts: list[str] = []
    for role, text in selected:
        if role == "":
            parts.append(f"[... {omitted} messages omitted ...]")
            continue
        truncated = text[:_MAX_MSG_CHARS] + ("..." if len(text) > _MAX_MSG_CHARS else "")
        parts.append(f"{role.upper()}: {truncated}")

    result = "\n\n".join(parts)
    return result[:_MAX_TOTAL_CHARS]


async def generate_summary(transcript_path: Path) -> str | None:
    """Generate a 1-sentence summary of a session transcript via Claude API.

    Uses Claude Code subscription credentials (no ANTHROPIC_API_KEY needed).
    Returns None on any failure — callers should fall back to existing summary.
    """
    transcript = strip_transcript(transcript_path)
    if not transcript:
        logger.debug("No transcript content to summarize for {}", transcript_path)
        return None

    prompt = (
        "Summarize this Claude Code session in one short sentence (max 10 words).\n"
        "Focus on what the user is working on, not technical details.\n\n"
        f"Transcript:\n{transcript}"
    )

    try:
        client = anthropic.AsyncAnthropic()
        response = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=10.0,
        )
        text = response.content[0].text.strip()
        logger.debug("Generated summary for {}: {}", transcript_path.stem, text)
        return text
    except anthropic.AuthenticationError as e:
        logger.warning("Anthropic auth failed — Claude subscription required: {}", e)
        return None
    except anthropic.APIError as e:
        logger.warning("Anthropic API error for {}: {}", transcript_path.stem, e)
        return None
    except asyncio.TimeoutError:
        logger.warning("Summary generation timed out for {}", transcript_path.stem)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sources_summarize.py -v
```

Expected: All 7 tests pass.

- [ ] **Step 5: Run linting/type checks**

```bash
uv run ruff format src/cctop/sources/summarize.py && uv run ruff check src/cctop/sources/summarize.py && uv run pyright src/cctop/sources/summarize.py
```

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/cctop/sources/summarize.py tests/test_sources_summarize.py
git commit -m "feat: add summarize.py with strip_transcript and generate_summary"
```

---

## Task 4: Add `generate_summary` tests (mocked API)

**Files:**
- Modify: `tests/test_sources_summarize.py`

- [ ] **Step 1: Add mocked API tests**

Add to `tests/test_sources_summarize.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from cctop.sources.summarize import generate_summary


@pytest.mark.asyncio
async def test_generate_summary_success(tmp_path: Path) -> None:
    """Returns summary string on success."""
    t = tmp_path / "sess.jsonl"
    _write_transcript(t, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "Fix the login bug"}]}},
    ])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Fixing login authentication bug")]

    with patch("cctop.sources.summarize.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        result = await generate_summary(t)

    assert result == "Fixing login authentication bug"


@pytest.mark.asyncio
async def test_generate_summary_auth_error(tmp_path: Path) -> None:
    """Returns None on AuthenticationError."""
    t = tmp_path / "sess.jsonl"
    _write_transcript(t, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "Hello"}]}},
    ])

    with patch("cctop.sources.summarize.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.AuthenticationError(
                message="No auth", response=MagicMock(), body={}
            )
        )

        result = await generate_summary(t)

    assert result is None


@pytest.mark.asyncio
async def test_generate_summary_timeout(tmp_path: Path) -> None:
    """Returns None on timeout."""
    t = tmp_path / "sess.jsonl"
    _write_transcript(t, [
        {"type": "user", "message": {"content": [{"type": "text", "text": "Hello"}]}},
    ])

    with patch("cctop.sources.summarize.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(side_effect=asyncio.TimeoutError())

        result = await generate_summary(t)

    assert result is None


@pytest.mark.asyncio
async def test_generate_summary_empty_transcript(tmp_path: Path) -> None:
    """Returns None without making API call when transcript is empty."""
    t = tmp_path / "sess.jsonl"
    t.write_text("")

    with patch("cctop.sources.summarize.anthropic.AsyncAnthropic") as mock_client_cls:
        result = await generate_summary(t)
        mock_client_cls.assert_not_called()

    assert result is None
```

Also add `asyncio_mode = "auto"` to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
markers = ["contract: contract tests that run real Claude Code sessions (require claude CLI, cost tokens)"]
addopts = "-m 'not contract'"
asyncio_mode = "auto"
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_sources_summarize.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sources_summarize.py pyproject.toml
git commit -m "test: add mocked API tests for generate_summary"
```

---

## Task 5: Update `SessionDetail` to accept and render `llm_summary`

**Files:**
- Modify: `src/cctop/widgets/session_detail.py`

- [ ] **Step 1: Implement the change**

Replace the contents of `src/cctop/widgets/session_detail.py`:

```python
from rich.text import Text
from textual.widgets import Static

from cctop.models import Session

_GENERATING = "Generating..."


class SessionDetail(Static):
    """Expanded detail view for a session."""

    def __init__(self, session: Session, llm_summary: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.llm_summary = llm_summary

    def render(self) -> Text:
        s = self.session
        lines = Text()

        if s.pr_url and s.pr_title:
            lines.append(f"  │  PR: {s.pr_title}\n", style="blue")
            lines.append(f"  │  {s.pr_url}\n", style="dim blue")

        # LLM summary takes priority; "Generating..." shown dim
        display_summary = self.llm_summary or s.summary
        if display_summary:
            if display_summary == _GENERATING:
                lines.append(f"  │  Summary: {display_summary}\n", style="dim")
            else:
                lines.append(f"  │  Summary: {display_summary}\n", style="white")
        elif s.first_prompt:
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

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: All tests pass.

- [ ] **Step 3: Run linting/type checks**

```bash
uv run ruff format src/cctop/widgets/session_detail.py && uv run ruff check src/cctop/widgets/session_detail.py && uv run pyright src/cctop/widgets/session_detail.py
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add src/cctop/widgets/session_detail.py
git commit -m "feat: SessionDetail accepts llm_summary, renders Generating... dim"
```

---

## Task 6: Update `SessionList` with LLM summary caching and workers

**Files:**
- Modify: `src/cctop/widgets/session_list.py`

This is the core integration — `SessionList` fires background workers on expand and caches results in `_llm_summaries`.

- [ ] **Step 1: Implement the full updated `SessionList`**

Replace `src/cctop/widgets/session_list.py`:

```python
from pathlib import Path

from loguru import logger
from textual.binding import Binding
from textual.containers import VerticalScroll

from cctop.models import Session
from cctop.sources.index import find_transcript_path
from cctop.sources.summarize import generate_summary
from cctop.widgets.session_detail import SessionDetail
from cctop.widgets.session_row import SessionRow

_GENERATING = "Generating..."


class SessionList(VerticalScroll):
    """Scrollable list of sessions with expand/collapse and LLM summaries."""

    BINDINGS = [
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("enter", "toggle_expand", "Expand/Collapse"),
        Binding("r", "regenerate_summary", "Regenerate summary", show=False),
    ]

    def __init__(self, projects_dir: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: list[Session] = []
        self._cursor: int = 0
        self._expanded: set[str] = set()
        self._llm_summaries: dict[str, str] = {}
        self._projects_dir = projects_dir or Path.home() / ".claude" / "projects"

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
                llm_summary = self._llm_summaries.get(session.session_id)
                self.mount(SessionDetail(session, llm_summary=llm_summary))

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
        session = self._sessions[self._cursor]
        sid = session.session_id
        if sid in self._expanded:
            self._expanded.discard(sid)
            self._rebuild()
        else:
            self._expanded.add(sid)
            if sid not in self._llm_summaries:
                self._start_summary_generation(session)
            else:
                self._rebuild()

    def action_regenerate_summary(self) -> None:
        """Regenerate the LLM summary for the currently expanded session."""
        if not self._sessions:
            return
        session = self._sessions[self._cursor]
        sid = session.session_id
        # Guard: only act if this session is expanded
        if sid not in self._expanded:
            return
        self._llm_summaries.pop(sid, None)
        self._start_summary_generation(session)

    def _start_summary_generation(self, session: Session) -> None:
        """Set the generating sentinel, rebuild, then fire the worker."""
        sid = session.session_id
        self._llm_summaries[sid] = _GENERATING
        self._rebuild()
        self.run_worker(self._generate_and_apply(session), exit_on_error=False)

    async def _generate_and_apply(self, session: Session) -> None:
        """Background worker: find transcript, call Claude, update cache."""
        sid = session.session_id
        transcript_path = find_transcript_path(
            self._projects_dir,
            session.cwd,
            session.session_id,
            session.started_at,
        )
        if transcript_path is None:
            logger.warning("No transcript found for session {}", sid)
            self._llm_summaries.pop(sid, None)
            self._rebuild()
            return

        summary = await generate_summary(transcript_path)
        if summary:
            self._llm_summaries[sid] = summary
        else:
            logger.warning("Summary generation failed for session {}", sid)
            self._llm_summaries.pop(sid, None)
        self._rebuild()
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: All tests pass.

- [ ] **Step 3: Run linting/type checks**

```bash
uv run ruff format src/cctop/widgets/session_list.py && uv run ruff check src/cctop/widgets/session_list.py && uv run pyright src/cctop/widgets/session_list.py
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add src/cctop/widgets/session_list.py
git commit -m "feat: SessionList fires LLM summary workers on expand, r to regenerate"
```

---

## Task 7: Pass `projects_dir` to `SessionList` from `app.py`

**Files:**
- Modify: `src/cctop/app.py`

`SessionManager` stores `_projects_dir` internally. We need to expose it so `SessionList` can use the same path.

- [ ] **Step 1: Expose `projects_dir` from `SessionManager` and pass to `SessionList`**

In `src/cctop/sources/merger.py`, add a property (no new imports needed):

```python
@property
def projects_dir(self) -> Path:
    return self._projects_dir
```

In `src/cctop/app.py`, update `compose()` to pass `projects_dir`:

```python
def compose(self) -> ComposeResult:
    yield Header()
    yield SessionList(projects_dir=self._manager.projects_dir)
    yield Footer()
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: All tests pass.

- [ ] **Step 3: Run linting/type checks on modified files**

```bash
uv run ruff format src/cctop/app.py src/cctop/sources/merger.py && uv run ruff check src/cctop/app.py src/cctop/sources/merger.py && uv run pyright src/cctop/app.py src/cctop/sources/merger.py
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add src/cctop/app.py src/cctop/sources/merger.py
git commit -m "feat: pass projects_dir from SessionManager to SessionList"
```

---

## Task 8: Full validation

- [ ] **Step 1: Run all tests**

```bash
uv run pytest -v
```

Expected: All tests pass.

- [ ] **Step 2: Run full linting suite**

```bash
uv run ruff format src/ tests/ && uv run ruff check src/ tests/ && uv run pyright src/
```

Expected: No errors.

- [ ] **Step 3: Smoke test the app**

```bash
uv run cctop --recent 1h
```

Expected: App launches. Expanding an active session shows "Summary: Generating..." briefly, then shows a real 1-sentence summary. Pressing `r` regenerates the summary.

- [ ] **Step 4: Final commit if any fixups needed**

```bash
git add -p
git commit -m "fix: post-integration fixups"
```
