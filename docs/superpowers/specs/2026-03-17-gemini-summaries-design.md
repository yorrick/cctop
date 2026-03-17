# LLM-Generated Session Summaries via Gemini API

## Problem

cctop's session summaries are useless for active sessions. Claude Code's `sessions-index.json` has excellent AI-generated summaries (98% coverage), but only for completed sessions. Active sessions fall back to `first_prompt[:120]`, which is often system-injected boilerplate like "Base directory for this skill: /Users/..." — not the user's actual intent.

## Solution

Generate on-demand summaries via the Gemini API (gemini-2.0-flash-lite) when a session row is expanded. Strip the transcript down to a compact representation before sending to the LLM.

## Behavior

### Trigger
- Summary is generated when a session row is **expanded** (Enter key) and the session has no real summary (i.e., the current summary is a first-prompt fallback or None).
- A keybinding (`s`) regenerates the summary for the currently expanded session.
- While generating, the detail view shows "Summary: Generating..." with a dim style.

### Caching
- Generated summaries are cached in memory on the `Session` object (`session.summary`).
- Cache persists across refresh cycles (already handled by merger.py for summary/PR data).
- Cache is invalidated when the user explicitly requests regeneration via `s`.

### Fallback
- If `GEMINI_API_KEY` is not set, no generation is attempted — existing behavior (first-prompt fallback) is preserved.
- If the API call fails (timeout, error, rate limit), the first-prompt fallback is kept and a log warning is emitted.
- Timeout: 10 seconds per API call.

## Transcript Stripping

Before sending to Gemini, the transcript is stripped to minimize tokens:

1. **Extract only user and assistant messages** — skip progress, queue-operation, file-history-snapshot, system entries.
2. **Strip system tags from user messages** — remove `<system-reminder>`, `<local-command-caveat>`, `<command-name>`, `<command-args>`, `<task-notification>`, etc. (reuse existing `_SYSTEM_TAG_RE` from index.py).
3. **Take first 3 + last 3 messages** — captures session intent and current state. Skip the middle to stay compact.
4. **Truncate individual messages to 500 chars** — long messages (tool output, code blocks) get cut.
5. **Add a separator** `[... N messages omitted ...]` between first and last groups if messages were skipped.
6. **Target: under 3000 chars total** for the stripped transcript.

## Gemini API Integration

### Model
`gemini-2.0-flash-lite` — cheapest, fastest, sufficient for 1-line summary generation.

### HTTP Client
Add `httpx` to dependencies for async HTTP. Use it in an async method following the same pattern as `_poll_slow()` / `lookup_pr()`.

### API Call
```
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent
Header: x-goog-api-key: $GEMINI_API_KEY
Body: { "contents": [{ "parts": [{ "text": "<prompt>" }] }] }
```

### Prompt
```
Summarize this Claude Code session in one short sentence (max 10 words).
Focus on what the user is working on, not technical details.

Transcript:
<stripped transcript>
```

### Response Parsing
Extract `response.json()["candidates"][0]["content"]["parts"][0]["text"]` and strip whitespace.

## Architecture

### New file: `src/cctop/sources/summarize.py`
- `async def generate_summary(transcript_path: Path, session_id: str) -> str | None`
  - Reads transcript, strips it, calls Gemini, returns summary or None on failure.
- `def strip_transcript(transcript_path: Path) -> str`
  - Implements the stripping logic (first 3 + last 3 messages, truncated, tags stripped).
- Uses `httpx.AsyncClient` for the API call.

### Modified: `src/cctop/widgets/session_list.py`
- On expansion, if session has no real summary (or summary looks like a first-prompt fallback), schedule summary generation.
- Use `asyncio.create_task()` to run generation without blocking the UI.
- On completion, update `session.summary` and call `_rebuild()` to refresh the detail view.

### Modified: `src/cctop/app.py`
- Add `s` keybinding to regenerate summary for expanded session.
- Pass through to SessionList.

### Modified: `pyproject.toml`
- Add `httpx` to dependencies.

### No changes to: `models.py`, `merger.py`, `session_detail.py`
- Session model already has `summary: str | None` field.
- SessionDetail already renders summary when present.
- Merger already preserves summary across refresh cycles.

## Testing

- Unit test `strip_transcript()` with a synthetic JSONL file containing system tags, long messages, and various entry types.
- Unit test the prompt construction.
- Integration test the Gemini API call with a mock (httpx mock or respx).
- Contract test: verify that `strip_transcript` on a real transcript produces output under 3000 chars.

## Environment
- `GEMINI_API_KEY` env var required (already set in user's environment).
- Graceful degradation: no key = no generation, no error.
