# Session Name Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the `claude --name <label>` session name in a new `NAME` column in the cctop TUI, reading it from the `custom-title` entry in the transcript `.jsonl` file.

**Architecture:** The `customTitle` field is stored as the first line of the session's `.jsonl` transcript. We extend `IndexEntry` to carry it, propagate it through `Session.name` in the merger, and render it as a 16-char column in `SessionRow` and `Header`.

**Tech Stack:** Python 3.12, Pydantic, Textual (TUI), pytest, uv

---

## File Map

| File | Change |
|------|--------|
| `src/cctop/sources/index.py` | Add `name` to `IndexEntry`; extract `customTitle` from transcript; fix early-exit guard |
| `src/cctop/models.py` | Add `name: str \| None = None` to `Session` |
| `src/cctop/sources/merger.py` | Carry `name` through constructors and two enrichment sites |
| `src/cctop/widgets/session_row.py` | Render `NAME` column (16 chars) |
| `src/cctop/widgets/header.py` | Add `NAME` column header |
| `tests/test_sources_index.py` | New tests for `customTitle` extraction |
| `tests/test_sources_merger.py` | New tests for `name` propagation and survival across refresh |
| `tests/widgets/__init__.py` | New file: empty, makes `tests/widgets/` a package |
| `tests/widgets/test_session_row.py` | New file: tests for NAME column rendering |
| `tests/widgets/test_header.py` | New file: test for NAME header label |

---

## Task 1: Extend `IndexEntry` to carry `name` and extract from transcript

**Files:**
- Modify: `src/cctop/sources/index.py`
- Test: `tests/test_sources_index.py`

- [ ] **Step 1: Write failing tests for `customTitle` extraction**

Add these tests to `tests/test_sources_index.py`. Import `_read_transcript_metadata` (it's currently imported indirectly via merger; add a direct import):

```python
import json
from pathlib import Path

from cctop.sources.index import _read_transcript_metadata


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
        json.dumps({"type": "custom-title", "customTitle": "early-session", "sessionId": "abc-123"})
        + "\n"
    )
    entry = _read_transcript_metadata("abc-123", transcript)
    assert entry is not None
    assert entry.name == "early-session"
    assert entry.message_count == 0


def test_read_transcript_name_none_when_no_custom_title(tmp_path: Path) -> None:
    """Returns IndexEntry with name=None when transcript has no custom-title."""
    transcript = tmp_path / "abc-123.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
    )
    entry = _read_transcript_metadata("abc-123", transcript)
    assert entry is not None
    assert entry.name is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/yorrickjansen/work/cctop
uv run pytest tests/test_sources_index.py::test_read_transcript_extracts_custom_title tests/test_sources_index.py::test_read_transcript_name_set_even_with_no_messages tests/test_sources_index.py::test_read_transcript_name_none_when_no_custom_title -v
```

Expected: FAIL — `IndexEntry` has no `name` attribute and `_read_transcript_metadata` is not importable from this test.

- [ ] **Step 3: Implement the changes in `sources/index.py`**

**3a.** Add `name` field to `IndexEntry` (after `message_count`):
```python
name: str | None = None
```

**3b.** In `_read_transcript_metadata`, introduce `name` variable and handle `custom-title`. The full updated function body:

```python
def _read_transcript_metadata(session_id: str, transcript_path: Path) -> IndexEntry | None:
    """Extract metadata from a session transcript JSONL file."""
    first_prompt: str | None = None
    message_count = 0
    git_branch: str | None = None
    summary: str | None = None
    name: str | None = None                          # NEW

    try:
        with transcript_path.open() as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "custom-title":        # NEW
                    name = data.get("customTitle")    # NEW

                elif msg_type == "user":
                    message_count += 1
                    if first_prompt is None:
                        text = _extract_user_text(data)
                        if text:
                            first_prompt = text[:200]

                elif msg_type == "assistant":
                    message_count += 1

                elif msg_type == "summary":
                    summary = data.get("summary", data.get("text"))

    except OSError as e:
        logger.warning("Failed to read transcript {}: {}", transcript_path, e)
        return None

    # Return None only if there is truly nothing useful              # CHANGED
    if first_prompt is None and message_count == 0 and name is None: # CHANGED
        return None

    if summary is None and first_prompt:
        summary = first_prompt[:120] + ("..." if len(first_prompt) > 120 else "")

    return IndexEntry.model_validate(
        {
            "sessionId": session_id,
            "summary": summary,
            "firstPrompt": first_prompt,
            "gitBranch": git_branch,
            "messageCount": message_count,
            "name": name,                             # NEW
        }
    )
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
uv run pytest tests/test_sources_index.py::test_read_transcript_extracts_custom_title tests/test_sources_index.py::test_read_transcript_name_set_even_with_no_messages tests/test_sources_index.py::test_read_transcript_name_none_when_no_custom_title -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Run full test suite to confirm nothing broken**

```bash
uv run pytest -x -q
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/cctop/sources/index.py tests/test_sources_index.py
git commit -m "feat: extract customTitle from transcript into IndexEntry.name"
```

---

## Task 2: Add `name` to `Session` model

**Files:**
- Modify: `src/cctop/models.py`

- [ ] **Step 1: Add `name` field to `Session`**

Open `src/cctop/models.py` and add after the `summary` field (or alongside optional fields):
```python
name: str | None = None
```

- [ ] **Step 2: Run pyright to verify type correctness**

```bash
uv run pyright
```

Expected: no errors.

- [ ] **Step 3: Run tests**

```bash
uv run pytest -x -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/cctop/models.py
git commit -m "feat: add name field to Session model"
```

---

## Task 3: Propagate `name` through the merger

**Files:**
- Modify: `src/cctop/sources/merger.py`
- Test: `tests/test_sources_merger.py`

- [ ] **Step 1: Write failing merger tests**

Add these tests to `tests/test_sources_merger.py`:

```python
def test_merge_enriches_name_from_transcript(tmp_path: Path) -> None:
    """Session.name is populated from customTitle in the transcript."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    project_dir = projects_dir / "-tmp-test"
    project_dir.mkdir()
    transcript = project_dir / "abc-123.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "my-feature", "sessionId": "abc-123"})
        + "\n"
        + json.dumps({"type": "user", "message": {"content": "hello"}})
        + "\n"
    )

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()

    assert mgr.sessions[0].name == "my-feature"


def test_name_survives_refresh(tmp_path: Path) -> None:
    """Session.name set from transcript must persist across refresh() calls."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    _write_session_file(sessions_dir, os.getpid(), "abc-123", "/tmp/test")

    project_dir = projects_dir / "-tmp-test"
    project_dir.mkdir()
    transcript = project_dir / "abc-123.jsonl"
    transcript.write_text(
        json.dumps({"type": "custom-title", "customTitle": "my-feature", "sessionId": "abc-123"})
        + "\n"
        + json.dumps({"type": "user", "message": {"content": "hello"}})
        + "\n"
    )

    mgr = SessionManager(sessions_dir=sessions_dir, projects_dir=projects_dir)
    mgr.refresh()
    assert mgr.sessions[0].name == "my-feature"

    # Second refresh: name must survive even if transcript is not re-read
    mgr.refresh()
    assert mgr.sessions[0].name == "my-feature"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sources_merger.py::test_merge_enriches_name_from_transcript tests/test_sources_merger.py::test_name_survives_refresh -v
```

Expected: FAIL — `name` not yet propagated.

- [ ] **Step 3: Implement merger changes**

**Site 1: `refresh()` — carry `name` from existing and set from entry**

In the alive-path `Session(...)` constructor (around line 69), add:
```python
name=existing.name if existing else None,
```
alongside `pr_url` and `pr_title`.

In the offline-path `Session(...)` constructor (around line 85), add:
```python
name=existing.name if existing else None,
```

After the `if entry:` block (which ends after setting `message_count`, around line 125), add this **outside** the block:
```python
if entry and entry.name:
    session.name = entry.name
```

**Site 2: `_resolve_session()` CWD-based enrichment**

Find the existing guard (around line 198):
```python
if session and not session.summary:
```
Change it to:
```python
if session and (not session.summary or not session.name):
```

Inside that block, after the `session.message_count = entry.message_count` line, add:
```python
if entry.name:
    session.name = entry.name
```

- [ ] **Step 4: Run the new tests to verify they pass**

```bash
uv run pytest tests/test_sources_merger.py::test_merge_enriches_name_from_transcript tests/test_sources_merger.py::test_name_survives_refresh -v
```

Expected: both PASS.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -x -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/cctop/sources/merger.py tests/test_sources_merger.py
git commit -m "feat: propagate session name through merger"
```

---

## Task 4: Render `NAME` column in `SessionRow` and `Header`

**Files:**
- Modify: `src/cctop/widgets/session_row.py`
- Modify: `src/cctop/widgets/header.py`
- Create: `tests/widgets/__init__.py`
- Create: `tests/widgets/test_session_row.py`
- Create: `tests/widgets/test_header.py`

**Note:** `SessionRow.render()` returns a Rich `Text` object and works fine outside a Textual app context — verified empirically.

- [ ] **Step 1: Create `tests/widgets/` package**

```bash
mkdir -p /Users/yorrickjansen/work/cctop/tests/widgets
touch /Users/yorrickjansen/work/cctop/tests/widgets/__init__.py
```

- [ ] **Step 2: Write failing widget tests**

Create `tests/widgets/test_session_row.py`:

```python
from datetime import datetime, timezone

from cctop.models import Session
from cctop.widgets.session_row import SessionRow


def _make_session(**kwargs) -> Session:  # type: ignore[no-untyped-def]
    defaults = dict(
        session_id="abc-123",
        pid=12345,
        cwd="/tmp/test",
        project_name="test",
        status="idle",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_activity=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Session(**defaults)


def test_session_row_shows_name_when_set() -> None:
    session = _make_session(name="my-feature")
    row = SessionRow(session)
    rendered = row.render().plain
    assert "my-feature" in rendered


def test_session_row_shows_dash_when_name_none() -> None:
    session = _make_session(name=None)
    row = SessionRow(session)
    rendered = row.render().plain
    # The NAME column should show the em-dash placeholder
    assert "—" in rendered


def test_session_row_truncates_long_name() -> None:
    session = _make_session(name="a" * 20)
    row = SessionRow(session)
    rendered = row.render().plain
    # Should be truncated: first 15 chars + ellipsis
    assert "aaaaaaaaaaaaaaa…" in rendered
    # The full 20-char name should NOT appear
    assert "a" * 20 not in rendered
```

Create `tests/widgets/test_header.py`:

```python
from cctop.widgets.header import Header


def test_header_includes_name_label() -> None:
    header = Header()
    rendered = header.render().plain
    assert "NAME" in rendered
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/widgets/test_session_row.py tests/widgets/test_header.py -v
```

Expected: FAIL — no NAME column yet.

- [ ] **Step 4: Update `session_row.py` to render NAME column**

In `SessionRow.render()`, after `line.append(f" {icon} ", style=color)` and before the PROJECT append, insert:

```python
name_display = s.name[:15] + "…" if s.name and len(s.name) > 15 else (s.name or "—")
if s.name:
    line.append(f"{name_display:<16}")
else:
    line.append(f"{name_display:<16}", style="dim")
```

- [ ] **Step 5: Update `header.py` to add NAME column header**

In `Header.render()`, in the column headers section, after `line.append("     ", style="dim")` and before `line.append(f"{'PROJECT':<24}", ...)`, insert:

```python
line.append(f"{'NAME':<16}", style="dim bold")
```

- [ ] **Step 6: Run the new tests to verify they pass**

```bash
uv run pytest tests/widgets/test_session_row.py tests/widgets/test_header.py -v
```

Expected: all 4 PASS.

- [ ] **Step 7: Run full test suite and all quality checks**

```bash
uv run ruff format src/ tests/ && uv run ruff check src/ tests/ && uv run pyright && uv run pytest -q
```

Expected: all pass, no errors.

- [ ] **Step 8: Commit**

```bash
git add src/cctop/widgets/session_row.py src/cctop/widgets/header.py tests/widgets/__init__.py tests/widgets/test_session_row.py tests/widgets/test_header.py
git commit -m "feat: add NAME column to session list (issue #5)"
```

---

## Final Validation

- [ ] Run the full quality suite one more time:

```bash
uv run ruff format src/ tests/ && uv run ruff check src/ tests/ && uv run pyright && uv run pytest -v
```

Expected: all green.
