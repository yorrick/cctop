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
2. **PID walk-up** reliably maps Claude Code PIDs to iTerm2 sessions — process chain is typically 3 hops (`claude → fish → login`), but the walk is unbounded (walks all the way to PID 1 or until a match). Different shell setups (bash, tmux wrapping, direnv, nix-shell) may add intermediate hops.
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

    @property
    def available(self) -> bool:
        """Whether iTerm2 integration is available."""
        return self._available

    async def connect(self) -> None:
        """Try to connect to iTerm2 API. Sets _available=False on failure."""
        # Lazy import iterm2 AND psutil (try/except ImportError for both)
        # If either is missing, _available = False and return
        # Attempt connection (catch exception if API server disabled)
        # Silent failure — _available remains False
        # Log connection result via loguru (debug level)

    async def activate_session(self, claude_pid: int) -> bool:
        """Focus the iTerm2 pane running the given Claude Code process.

        1. Query iTerm2 for all sessions + root PIDs
        2. Walk up from claude_pid via psutil to find ancestor match
           (unbounded walk — continues until PID 1 or match found)
        3. Call session.async_activate() on the matched session

        Returns True if focused, False if no matching pane found.
        Logs walk-up misses via loguru (debug level).
        """
```

- Instantiated once in `CctopApp` as `self._iterm_bridge`
- `connect()` called during `on_mount()` — non-blocking, failure is silent
- `activate_session()` called from the Enter key handler
- All `iterm2` and `psutil` imports are lazy (inside try/except) so both packages remain optional
- Uses `loguru` for debug logging on connection failures and walk-up misses, consistent with `github.py`
- **No reconnection:** if iTerm2 is restarted, cctop must be restarted too. Reconnection is not worth the complexity for MVP.

### Keybinding Changes

| Key | Current | New |
|-----|---------|-----|
| Enter | Expand/collapse detail | Focus iTerm2 pane (via `action_focus_iterm`) |
| Space | (unbound) | Expand/collapse detail (via `action_toggle_expand`) |

**Implementation:** Enter is always bound to `action_focus_iterm` in `SessionList.BINDINGS`. The action checks `self.app._iterm_bridge.available` — if iTerm2 is not available, the action is a no-op (no error, no notification). This avoids conditional binding complexity.

**Data flow for Enter:**
1. `SessionList` handles the Enter key binding → `async def action_focus_iterm(self) -> None`
2. Guard: `if not self._sessions: return` (same pattern as `action_toggle_expand`)
3. Guard: `if not self.app._iterm_bridge.available: return` (no-op if iTerm2 unavailable)
4. Gets the currently selected `Session` from `self._sessions[self._cursor]`
5. Calls `await self.app._iterm_bridge.activate_session(session.pid)`
6. If returns `False`, calls `self.app.notify("No iTerm2 pane found for this session")`

Note: offline sessions (dead PID) will naturally fall through to "no match" — `psutil` raises `NoSuchProcess`, `activate_session` catches it and returns `False`.

**Updates required:**
- `SessionList.BINDINGS`: Change Enter from `action_toggle_expand` to `action_focus_iterm`, add Space for `action_toggle_expand`
- `app.py` help text (`action_show_help`): Update "Enter" to "Focus iTerm2 pane" and add "Space" → "Expand / collapse"
- `footer.py`: Update labels — `("Enter", "focus pane")`, `("Space", "expand/collapse")`

### Status Feedback

- **Success:** No message — the tab switch itself is the feedback
- **No match (orphaned session):** Textual `notify()` toast: "No iTerm2 pane found for this session"
- **Not connected / not installed:** Enter does nothing silently (no-op)

### Dependency Strategy

- `iterm2` and `psutil>=5.0` added as optional extras in `pyproject.toml`: `cctop[iterm2]`
- Both are imported lazily and guarded together — if either import fails, `_available = False`
- Detection is purely connect-and-see — no env var checks or `$TERM_PROGRAM` sniffing
- If imports fail or connection fails, the feature is disabled with zero impact on normal operation

## Files Changed

| File | Change |
|------|--------|
| `src/cctop/sources/iterm2.py` | New module: `ITermBridge` class with lazy imports and loguru logging |
| `src/cctop/app.py` | Instantiate `ITermBridge`, connect on mount; update `action_show_help` text for Enter/Space |
| `src/cctop/widgets/session_list.py` | Add `action_focus_iterm` bound to Enter; rebind Space to `action_toggle_expand`; add `action_focus_iterm` method accessing `self.app._iterm_bridge` |
| `src/cctop/widgets/footer.py` | Update keybinding labels for Enter and Space |
| `pyproject.toml` | Add `[iterm2]` optional extra with `iterm2` and `psutil` |
| `tests/test_sources_iterm2.py` | Unit tests for `ITermBridge` (mocked iTerm2 API and psutil) |
| `tests/widgets/test_session_list.py` | Keybinding tests for Enter/Space |

## Testing Strategy

- **Unit tests:** Mock `iterm2` connection and session objects; verify PID walk-up logic, activate calls, graceful failure when packages not installed, graceful failure when no pane match
- **Keybinding tests:** Verify Space expands/collapses, Enter triggers `action_focus_iterm`
- **No contract tests needed:** iTerm2 API is local-only, can't run in CI
