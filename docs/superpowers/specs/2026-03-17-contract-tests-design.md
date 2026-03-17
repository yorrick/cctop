# Contract Tests for Claude Code Data Ingestion

## Problem

cctop monitors Claude Code sessions by reading files on disk:
- PID files (`~/.claude/sessions/{pid}.json`)
- Hook events (`~/.cctop/data/events.jsonl`)
- Transcript files (`~/.claude/projects/{encoded_cwd}/{session_id}.jsonl`)
- Session index (`~/.claude/projects/{encoded_cwd}/sessions-index.json`)

The existing unit tests verify "given these synthetic files, produce the right state" but cannot catch "Claude Code changed what files it produces." This gap causes real bugs:

- **Offline false positive:** `session_end` hook event fires on `/clear` (not just process exit), causing cctop to mark a live session as offline.
- **Message count reset:** `/clear` truncates the transcript, so cctop shows 2 messages for a session that had hundreds.
- **Session ID mismatch:** PID file session ID differs from hook/transcript session ID; cctop's CWD-based mapping is fragile.

These bugs can only be caught by testing against Claude Code's actual behavior.

## Solution

Contract tests that run real `claude --print` sessions and verify:
1. **Raw contract:** What files/events Claude Code actually produces (documents the contract).
2. **Integration:** That cctop's `SessionManager` correctly ingests those real artifacts.

When a test fails, the failure point tells you whether Claude Code changed its behavior or cctop has a logic bug.

## Test Infrastructure

### File & Location

`tests/test_contract.py`, marked with `@pytest.mark.contract`.

Skipped by default. Run explicitly:
```bash
pytest -m contract
```

### Pytest Configuration

Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = ["contract: contract tests that run real Claude Code sessions (require claude CLI, cost tokens)"]
```

### Isolation Strategy

Each test gets:
- **Own working directory:** `tmp_path` (under `/private/var/...`, avoids macOS `/tmp` symlink issues)
- **Deterministic session ID:** `--session-id` with a known UUID per test
- **Isolated events file:** `CCTOP_DATA_DIR` set to a test-specific directory under `tmp_path`

This means:
- Transcript path is predictable: `~/.claude/projects/{encode_cwd(tmp_path)}/{uuid}.jsonl`
- Events don't pollute or collide with other sessions
- PID files in `~/.claude/sessions/` are ephemeral and keyed by PID (no collision risk)

### Cleanup

Fixture teardown:
- Removes transcript file from `~/.claude/projects/{encoded_tmp_path}/`
- Removes the encoded project directory if empty
- `tmp_path` (events, working dir) cleaned up automatically by pytest

### Timeouts

- Short sessions (`--print "say PONG"`): 30s subprocess timeout
- Long-lived sessions (bash script): 60s subprocess timeout
- Polling loops (PID file, events): 0.5s interval, 15s max

## Test Helpers

### `wait_for(predicate, *, timeout, interval, desc) -> T`

Polls a callable until it returns a truthy value. Raises `TimeoutError` with `desc` on expiry. Returns the truthy value for direct use.

### Event reading

Reads the test's isolated events JSONL file. Parses each line, optionally filters by session ID.

### PID file discovery

Scans `~/.claude/sessions/*.json` for a PID file whose `cwd` matches the test's `tmp_path`. Returns parsed data + liveness. Handles the fact that PID file session ID may differ from `--session-id`.

### Transcript reading

Reads `~/.claude/projects/{encode_cwd(tmp_path)}/{session_id}.jsonl`. Counts user/assistant messages, returns structured data.

### `background_claude` context manager

```python
@contextmanager
def background_claude(work_dir, session_id, prompt, events_dir) -> Generator[subprocess.Popen]:
```

Starts `claude --print` in a background subprocess. Yields the `Popen` object. On exit: SIGTERM, brief wait, SIGKILL if needed. Ensures cleanup even if assertions fail.

## Test Scenarios

### Test 1: `test_basic_lifecycle`

**Setup:** `claude --print --session-id <uuid> "say PONG"` from `tmp_path`.

**Raw contract assertions:**
- `session_start` event exists with `sid=<uuid>` and `cwd=<tmp_path>`
- `stop` event exists with `sid=<uuid>`
- `session_end` event exists with `sid=<uuid>`
- Event order: `session_start` before `stop` before `session_end`
- Transcript file exists at the expected path
- Transcript contains at least 1 `user` and 1 `assistant` message

**Integration assertions:**
- After the process exits, `SessionManager` does not show this session (PID file cleaned up, dead sessions evicted with `recent=0`)

### Test 2: `test_session_resumption`

**Setup:** Run `--print --session-id <uuid>`, then `--print --resume <uuid>`.

**Raw contract assertions:**
- Two `session_start` events with `sid=<uuid>`
- Two `session_end` events with `sid=<uuid>`
- Same transcript file appended to (not a new file created)
- Transcript contains 4 messages (2 user + 2 assistant)

### Test 3: `test_long_lived_session`

**Setup:** `claude --print --session-id <uuid> --dangerously-skip-permissions "Write a bash script that prints hello every 2 seconds for 20 seconds. Run it."` as background subprocess.

**While running (poll for conditions):**
- PID file exists in `~/.claude/sessions/`
- PID is alive
- `session_start` event exists
- `tool_start` events appear (for Bash tool)
- `SessionManager.refresh()` + `apply_events()` shows the session as `"working"` or `"idle"` (not `"offline"`)

**After it finishes:**
- PID file is cleaned up
- `session_end` event exists

### Test 4: `test_session_end_does_not_mean_process_dead`

**This test proves the current bug.** It currently fails and must be fixed.

**Setup:** Start a long-lived session (same as test 3) as a background subprocess.

**While running:**
- Wait for `session_start` event
- Wait for at least one `tool_start` event
- Manually inject a `session_end` event into the isolated events file (simulates `/clear` behavior)
- Call `SessionManager.refresh()` + `apply_events()`
- **Assert the session is NOT offline** (PID is still alive)

**Why inject rather than trigger `/clear`:** `/clear` cannot be triggered from `--print` mode. Injecting the event into the events file simulates exactly what the hook would write, which is what cctop actually reads.

### Test 5: `test_pid_file_cleanup_on_exit`

**Setup:** Run `--print --session-id <uuid> "say PONG"`.

**Assertions:**
- During execution (if catchable) or immediately after: identify the PID
- After process fully terminates (poll): PID file no longer exists
- `session_end` event was emitted

### Test 6: `test_session_id_mapping`

**Setup:** Start a long-lived session with `--session-id <uuid>` as a background subprocess. Inspect PID file while alive.

**Raw contract assertions:**
- PID file `sessionId` may differ from `<uuid>`
- Hook events use `<uuid>` as session ID
- Transcript is named `<uuid>.jsonl`

**Integration assertions:**
- `SessionManager` resolves events for `<uuid>` to the correct session via CWD-based mapping
- Session metadata (from transcript) is correctly associated

## Discovered Contract (from experiments)

These findings from live `claude --print` experiments document Claude Code's current behavior. The contract tests codify these as assertions:

| Behavior | Detail |
|----------|--------|
| PID file session ID vs hook session ID | Different. PID file gets an internal ID; hooks use the `--session-id` value (or Claude's own transcript ID). |
| PID file cwd | May reflect the parent shell's cwd, not the actual session cwd. |
| `session_end` semantics | Fires on normal exit, `/clear`, and process termination — not exclusively on process death. |
| PID file lifecycle | Created on session start, removed on SIGTERM/normal exit. Process may linger briefly after `--print` returns. |
| `--continue` / `--resume` | Reuses original session ID in hooks. Appends to same transcript file. |
| `sessions-index.json` | Not created for `--print` sessions. cctop falls back to transcript reading. |
| Transcript on `/clear` | Truncated/reset. Message count reflects only post-clear content. |
