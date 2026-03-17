# LLM-Generated Session Summaries via Claude API

## Problem

cctop's session summaries are useless for active sessions. Claude Code's `sessions-index.json` has excellent AI-generated summaries (98% coverage), but only for completed sessions. Active sessions fall back to `first_prompt[:120]`, which is often system-injected boilerplate like "Base directory for this skill: /Users/..." — not the user's actual intent.

## Solution

Generate on-demand summaries via the Claude API (claude-haiku-4-5) when a session row is expanded. Strip the transcript down to a compact representation before sending to the LLM. Use the user's Claude subscription — no separate API key required.

## Behavior

### Trigger
- Summary is generated when a session row is **expanded** (Enter key), once per session per app run.
- A keybinding (`r`) regenerates the summary for the currently expanded session (clears cache, fires new request). `r` has no existing binding conflict in `SessionList` or `app.py`.
- While generating, the detail view shows `Summary: Generating...` with a dim style.

### Caching
- `SessionList` tracks `_llm_summaries: dict[str, str]` — maps session_id → LLM-generated summary string.
- On expand: if `session_id not in _llm_summaries`, fire generation. Add the sentinel `"Generating..."` to `_llm_summaries` immediately (before any await) to prevent double-firing on rapid collapse/re-expand.
- On completion: update `_llm_summaries[session_id]` with the real summary and call `_rebuild()`.
- `r` keybinding: remove from `_llm_summaries`, trigger regen (which re-adds sentinel and fires again).
- `SessionDetail` receives the LLM summary separately and renders it in preference to `session.summary`.
- The merger continues to overwrite `session.summary` on each refresh — the LLM-generated value is kept exclusively in `SessionList._llm_summaries`, safe from merger overwrites.

### Fallback
- If the Anthropic SDK raises `AuthenticationError` (no subscription/key), remove from `_llm_summaries`, emit a log warning, and skip generation — existing `session.summary` (first-prompt fallback) is shown.
- If the API call fails (timeout, error, rate limit), remove from `_llm_summaries` and emit a log warning.
- Timeout: 10 seconds, enforced via `asyncio.wait_for(..., timeout=10.0)`.

## Transcript Stripping

Before sending to the API, the transcript is stripped to minimize tokens:

1. **Extract only user and assistant messages** — skip progress, queue-operation, file-history-snapshot, system entries.
2. **Strip system tags from user messages** — remove `<system-reminder>`, `<local-command-caveat>`, `<command-name>`, `<command-args>`, `<task-notification>`, etc. (reuse existing `_SYSTEM_TAG_RE` from `index.py`).
3. **Take first 3 + last 3 messages** — captures session intent and current state. Skip the middle to stay compact.
4. **Truncate individual messages to 500 chars** — long messages (tool output, code blocks) get cut.
5. **Add a separator** `[... N messages omitted ...]` between first and last groups if messages were skipped.
6. **Target: under 3000 chars total** for the stripped transcript.

`strip_transcript` reads the file synchronously (`def`, not `async def`). Transcripts are small enough (under 1 MB typical) that blocking the event loop briefly is acceptable. If this proves problematic, wrap with `asyncio.to_thread` in `generate_summary`.

## Claude API Integration

### Model
`claude-haiku-4-5` — fastest, cheapest, sufficient for 1-line summary generation.

### Auth
`anthropic.AsyncAnthropic()` with no explicit API key. The SDK detects Claude Code subscription credentials automatically (reads from `~/.claude/.credentials.json`). This is the same mechanism Claude Code itself uses. If no credentials are found, the SDK raises `AuthenticationError`, which is caught and handled gracefully.

Users who have `ANTHROPIC_API_KEY` set will use API key auth instead — this is acceptable.

### API Call
```python
client = anthropic.AsyncAnthropic()
response = await client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=50,
    messages=[{"role": "user", "content": prompt}],
)
summary = response.content[0].text.strip()
```

### Prompt
```
Summarize this Claude Code session in one short sentence (max 10 words).
Focus on what the user is working on, not technical details.

Transcript:
<stripped transcript>
```

## Architecture

### New file: `src/cctop/sources/summarize.py`
- `async def generate_summary(transcript_path: Path) -> str | None`
  - Reads transcript, strips it, calls Claude, returns summary string or None on failure.
  - Catches `anthropic.AuthenticationError`, `anthropic.APIError` (includes `APITimeoutError`) — returns None.
  - Timeout enforced via `asyncio.wait_for(client.messages.create(...), timeout=10.0)`, which raises `asyncio.TimeoutError` (also caught).
- `def strip_transcript(transcript_path: Path) -> str`
  - Implements the stripping logic (first 3 + last 3 messages, truncated, tags stripped).
  - Reads file synchronously; acceptable for typical transcript sizes.
- Imports `_SYSTEM_TAG_RE` from `index.py` directly.
- Uses `anthropic.AsyncAnthropic` for the API call.

### Modified: `src/cctop/sources/index.py`
- Add `find_transcript_path(projects_dir: Path, cwd: Path, session_id: str, started_at: datetime) -> Path | None`
  - Step 1: check `<projects_dir>/<encoded_cwd>/<session_id>.jsonl` — return if exists.
  - Step 2: scan the project dir for `.jsonl` files modified after `started_at - 5min`, pick the most-recently-modified one that is not `<session_id>.jsonl` — return that path. This is the same logic as `_find_active_transcript_entry` in `merger.py`, duplicated here to avoid a circular import (`merger.py` already imports from `index.py`).
  - The `_pid_sid_to_hook_sid` mapping (held in `SessionManager`) is not accessible here — this is an acceptable limitation covering only a minor edge case for resumed sessions.
  - Returns the actual `.jsonl` Path (the file that exists on disk). Caller passes `session.started_at`.

### Modified: `src/cctop/widgets/session_list.py`
- Add `_llm_summaries: dict[str, str]` to store LLM-generated summaries keyed by session_id.
- Accept `projects_dir: Path` in `__init__` so it can locate transcripts.
- Modify `_rebuild()`: pass `_llm_summaries.get(session.session_id)` to `SessionDetail` constructor.
- On expand: if `session_id not in _llm_summaries`, call `_start_summary_generation(session)`.
- `_start_summary_generation(session)` (synchronous, called from action handlers):
  - Set `_llm_summaries[session_id] = "Generating..."` immediately (no await yet).
  - Call `_rebuild()` synchronously (same pattern as existing `action_toggle_expand` — `remove_children()` + `mount()` are fire-and-forget when called synchronously in Textual).
  - Use `self.run_worker(_generate_and_apply(session), exit_on_error=False)` for proper Textual worker lifecycle management. Do not use bare `asyncio.create_task()`. `exit_on_error=False` prevents unexpected exceptions in the worker from crashing the app.
- `_generate_and_apply(session)` (async worker):
  - Calls `find_transcript_path(projects_dir, session.cwd, session.session_id, session.started_at)` → `generate_summary`.
  - On success: `_llm_summaries[session_id] = summary`, call `_rebuild()`.
  - On failure (None returned): `del _llm_summaries[session_id]`, emit log warning, call `_rebuild()`.
- Add `r` keybinding → `action_regenerate_summary()`:
  - Guard: if the session at `_cursor` is not in `_expanded`, do nothing.
  - Remove current session from `_llm_summaries`.
  - Call `_start_summary_generation(session)`.

### Modified: `src/cctop/widgets/session_detail.py`
- Accept optional `llm_summary: str | None = None` in `__init__`.
- Render logic: use `llm_summary` if present (even `"Generating..."`), fall back to `session.summary`, then `session.first_prompt`.
- Render `"Generating..."` with dim style to distinguish from real summaries.

### Modified: `src/cctop/app.py`
- Pass `projects_dir` to `SessionList`.

### Modified: `pyproject.toml`
- Add `anthropic` to dependencies.

### No changes to: `models.py`, `merger.py`
- LLM summaries live in `SessionList._llm_summaries`, not on the `Session` model. The merger never touches this dict.

## Testing

- Unit test `strip_transcript()` with a synthetic JSONL file containing system tags, long messages, and various entry types.
- Unit test the prompt construction.
- Unit test `find_transcript_path()` — direct match case and active-transcript fallback case.
- Mock `anthropic.AsyncAnthropic` in `generate_summary` tests (no real API calls).
- Test `AuthenticationError` → returns None.
- Contract test: verify that `strip_transcript` on a real transcript produces output under 3000 chars.

## Auth Notes
- No `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` required — uses Claude Code subscription credentials from `~/.claude/.credentials.json`.
- Graceful degradation: `AuthenticationError` → log warning, remove from `_llm_summaries`, show first-prompt fallback.
- Users with `ANTHROPIC_API_KEY` set will use API key auth (acceptable).
