# Design: Show Session Name (--name) as a Column

**Date:** 2026-03-17
**Issue:** #5
**Status:** Approved

## Summary

When users start Claude Code with `claude --name <label>`, surface that label in a new `NAME` column in the cctop session list, positioned between the status icon and the `PROJECT` column.

## Background

Claude Code stores the session name as a `custom-title` entry — the first line of the session's `.jsonl` transcript file:

```json
{"type": "custom-title", "customTitle": "my-feature", "sessionId": "..."}
```

This was empirically verified: running `claude --name test-session-name --print "say hi"` produced exactly this structure at the start of the transcript. No other storage location (PID file, sessions-index.json) is used.

## Data Flow

```
transcript.jsonl (first line: type == "custom-title")
  └─ customTitle
       └─ IndexEntry.name
            └─ Session.name
                 └─ SessionRow NAME column (16 chars)
```

## Changes

### 1. `sources/index.py`

**`IndexEntry`**: Add `name: str | None = None` field.

**`_read_transcript_metadata()`**:
1. Introduce a `name: str | None = None` variable at the top of the function.
2. In the per-line loop, handle `type == "custom-title"` by setting `name = data.get("customTitle")`.
3. Fix the early-exit guard: the current function returns `None` when `message_count == 0 and first_prompt is None`. Change this to also return an `IndexEntry` when `name` is set — i.e., return `None` only if all three are absent.
4. Add `"name": name` to the `IndexEntry.model_validate(...)` call's dict at the end of the function.

**Note on `_find_active_transcript_entry()`**: This function calls `_read_transcript_metadata(session_id, best)` where `session_id` is the PID-file session ID (not the transcript's own ID). The returned `IndexEntry.session_id` will be the PID-file ID rather than the transcript ID — this is pre-existing behavior. Only `entry.name` (and other metadata fields) are consumed from this path; `entry.session_id` is not used by the enrichment code, so this is safe.

**`find_index_entry()`**: No change needed. The sessions-index.json path has no known key for session names; the `name` field will remain `None` from that path.

### 2. `models.py`

Add `name: str | None = None` to the `Session` model.

### 3. `sources/merger.py` — two enrichment sites

**Site 1: `refresh()`**

Step A — In both the alive-path `Session(...)` constructor and the offline-path constructor, add:
```python
name=existing.name if existing else None,
```
This carries the name forward from the previous cycle when the index lookup returns no entry (mirrors how `pr_url`/`pr_title` are preserved).

Step B — After the `if entry:` block (which sets `summary`, `first_prompt`, `git_branch`, `message_count`), add a **separate** guard outside that block:
```python
if entry and entry.name:
    session.name = entry.name
```
This must be outside the `if entry:` block so that `session.name` is never reset to `None` — it is only updated when `entry.name` is truthy. Do NOT add `session.name = entry.name` inside the existing `if entry:` block alongside the other field assignments, as that would overwrite a previously-read name with `None` whenever the transcript no longer has a `custom-title` entry.

**Site 2: `_resolve_session()` CWD-based enrichment**

The existing guard on this enrichment block is `if session and not session.summary`. This means if `summary` is already set, the entire block — including any `name` assignment — is skipped. Broaden the condition to:
```python
if session and (not session.summary or not session.name):
```
Then inside the block, add after the existing `message_count` assignment:
```python
if entry.name:
    session.name = entry.name
```

### 4. `widgets/session_row.py`

Add a `NAME` column (16 chars wide) between the status icon and `PROJECT`:
- When set: `name_display = name[:15] + "…" if len(name) > 15 else name`; render `f"{name_display:<16}"`
- When not set: render `f"{'—':<16}"` in dim style
- Invariant: rendered `name_display` is always ≤ 16 characters.

### 5. `widgets/header.py`

The existing column headers line starts with `"     "` (5 spaces, representing the icon prefix). After that prefix, add `f"{'NAME':<16}"` (dim bold) before `f"{'PROJECT':<24}"`. The 5-space prefix must remain unchanged so the header stays aligned with session rows.

### 6. `widgets/session_detail.py` — out of scope

The `name` field will not be added to the detail view in this change.

## Column Layout (after change)

| Column   | Width  | Notes                                        |
|----------|--------|----------------------------------------------|
| (icon)   | 3 + 1  | ` ● ` + trailing space                       |
| NAME     | 16     | `customTitle` truncated to 15+`…`, or `—`    |
| PROJECT  | 24     | Repository/directory name                    |
| BRANCH   | 22     | Git branch or worktree                       |
| STATUS   | 20     | `Working: <tool>` / `Idle` / `Offline`       |
| MSGS     | 4 + 2  | Right-aligned count + 2 spaces               |
| DURATION | 8      | Right-aligned total duration                 |
| (gap)    | 2      | Two spaces                                   |
| IDLE     | 6      | Right-aligned idle time                      |

**Total:** ~107 chars (was ~91).

## Display Rules

- Name set: `name_display = name[:15] + "…" if len(name) > 15 else name`; render `f"{name_display:<16}"`
- Name not set: render `f"{'—':<16}"` in dim style
- Header: `f"{'NAME':<16}"`, dim bold, before `PROJECT`

## Error Handling

- If the transcript first line is not valid JSON or lacks `customTitle`, `name` stays `None` (graceful degradation, no crash)
- Sessions without a transcript yet get `name = None`
- Sessions with a `custom-title` entry but zero messages: return `IndexEntry` with `name` set and `message_count=0` instead of `None`

## Testing

**`tests/sources/test_index.py`** (existing file)
- `_read_transcript_metadata` extracts `customTitle` when first line is `custom-title`
- `_read_transcript_metadata` returns `IndexEntry` with `name` set even when `message_count == 0`
- `_read_transcript_metadata` returns `name=None` for transcripts without `custom-title`

**`tests/sources/test_merger.py`** (existing file)
- When transcript contains `custom-title`, the resulting `Session.name` equals the `customTitle` value (model after existing `test_merge_enriches_from_index`)
- `name` is preserved from `existing` when index lookup returns no entry (model after existing `test_pr_data_survives_refresh`)
- `name` survives multiple `refresh()` calls once set (call `refresh()` twice, assert `session.name` unchanged on second call)

**`tests/widgets/` directory** (create if not present, with `__init__.py`)

**`tests/widgets/test_session_row.py`** (new file)
- Row renders NAME column with value when `session.name` is set
- Row renders `—` in NAME column when `session.name` is `None`
- Name longer than 15 chars is truncated to 15 chars + `…`

**`tests/widgets/test_header.py`** (new file)
- Header rendered output includes `NAME` label

## Acceptance Criteria

- Sessions started with `claude --name my-feature` show `my-feature` in the NAME column
- Sessions without a name show `—`
- Header row includes `NAME` label aligned with the column
- `name` is preserved across refresh cycles once read from the transcript
- All existing tests pass; new unit tests cover all cases above
