# iTerm2 Integration Design

**Issue:** #3 — iTerm2 integration: clickable session links and native tab awareness
**Date:** 2026-03-17
**Status:** Approved

## Goal

Allow cctop users on iTerm2 to press Enter on a session row and have iTerm2 switch focus to the tab/pane where that Claude Code session is running.

## Scope

**In scope (MVP):**
- Map Claude Code sessions to iTerm2 panes via PID walk-up
- Enter key focuses the matched iTerm2 pane
- Graceful degradation when iTerm2 is unavailable or pane is orphaned

**Out of scope (future):**
- Badges/notifications on state change
- OSC 8 clickable hyperlinks
- Cross-terminal support (tmux, Wezterm, etc.)

## Validated Assumptions

Tested empirically against the live iTerm2 setup:

1. **`session.async_activate()`** switches tab/pane focus instantly
2. **PID walk-up** reliably maps Claude Code PIDs to iTerm2 sessions — process chain is typically 3 hops: `claude → fish → login` (where `login` PID = iTerm2 session root PID)
3. **7/8 sessions matched** in testing; the one miss was a genuinely orphaned session whose pane had been closed
4. **iTerm2 Python API** connects via local Unix socket, fully async, negligible latency
5. **No caching needed** — querying the iTerm2 session list is essentially free (local socket)

## Architecture

### Approach: iTerm2 Python SDK

Uses the `iterm2` Python package (v2.14) which connects to iTerm2's API server via Unix domain socket. Requires "Enable Python API server" in iTerm2 Preferences > General > Magic.

Alternatives considered and rejected:
- **AppleScript:** Slower (subprocess per call), fragile string escaping, harder PID mapping
- **OSC 8 escape sequences:** Can't programmatically focus tabs, only opens URLs

### New Module: `sources/iterm2.py`

Single class `ITermBridge`:

```python
class ITermBridge:
    """Optional iTerm2 integration for focus switching."""

    _connection: iterm2.Connection | None
    _available: bool  # False if iterm2 not installed or API not enabled

    async def connect() -> None:
        """Try to connect to iTerm2 API. Sets _available=False on failure."""
        # Lazy import iterm2 (try/except ImportError)
        # Attempt connection (catch exception if API server disabled)
        # Silent failure — _available remains False

    async def activate_session(claude_pid: int) -> bool:
        """Focus the iTerm2 pane running the given Claude Code process.

        1. Query iTerm2 for all sessions + root PIDs
        2. Walk up from claude_pid via psutil to find ancestor match
        3. Call session.async_activate() on the matched session

        Returns True if focused, False if no matching pane found.
        """
```

- Instantiated once in `CctopApp`
- `connect()` called during `on_mount()` — non-blocking, failure is silent
- `activate_session()` called from the Enter key handler
- All `iterm2` imports are lazy so the package remains optional

### Keybinding Changes

| Key | Current | New |
|-----|---------|-----|
| Enter | Expand/collapse detail | Focus iTerm2 pane |
| Space | (unbound) | Expand/collapse detail |

- If iTerm2 is not available (not installed / not connected), Enter is simply unbound — no error
- Footer widget updates to reflect new bindings

### Status Feedback

- **Success:** No message — the tab switch itself is the feedback
- **No match (orphaned session):** Textual `notify()` toast: "No iTerm2 pane found for this session"
- **Not connected:** Enter does nothing silently

### Dependency Strategy

- `iterm2` and `psutil` added as optional extras in `pyproject.toml`: `cctop[iterm2]`
- Detection is purely connect-and-see — no env var checks or `$TERM_PROGRAM` sniffing
- If `import iterm2` fails or connection fails, the feature is disabled with zero impact on normal operation

## Files Changed

| File | Change |
|------|--------|
| `src/cctop/sources/iterm2.py` | New module: `ITermBridge` class |
| `src/cctop/app.py` | Instantiate `ITermBridge`, connect on mount, wire Enter handler |
| `src/cctop/widgets/session_list.py` | Enter calls `activate_session()`, Space takes over expand/collapse |
| `src/cctop/widgets/footer.py` | Update keybinding labels |
| `pyproject.toml` | Add `[iterm2]` optional extra with `iterm2` and `psutil` |
| `tests/test_sources_iterm2.py` | Unit tests for `ITermBridge` (mocked iTerm2 API) |
| `tests/widgets/test_session_list.py` | Keybinding tests for Enter/Space |

## Testing Strategy

- **Unit tests:** Mock `iterm2` connection and session objects; verify PID walk-up logic, activate calls, graceful failure paths
- **Keybinding tests:** Verify Space expands/collapses, Enter triggers activate
- **No contract tests needed:** iTerm2 API is local-only, can't run in CI
