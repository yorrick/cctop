# iTerm2: Focus Minimized/Background Windows

**Date:** 2026-03-18
**Issue:** #14
**Status:** Draft

## Problem

When an iTerm2 window is minimized, pressing Enter in cctop to focus a session shows "No iTerm2 pane found for this session" instead of un-minimizing the window and focusing the correct pane. Non-active tabs in visible windows work fine.

## Root Cause

`ITermBridge.activate_session()` calls `session.async_activate()` which activates the pane and switches tabs within a visible window, but does not un-minimize the containing window. The current code builds a `pid_map: dict[int, session]` that maps PIDs to iTerm2 session objects only — it discards the window and tab references.

## Design

### Change to `activate_session()` in `src/cctop/sources/iterm2.py`

1. **Track window and tab alongside session in the PID map.** Change from `pid_map: dict[int, session]` to `pid_map: dict[int, tuple[window, tab, session]]`.

2. **On PID match, activate in order:**
   - `await window.async_activate()` — un-minimizes the window and brings it to the foreground
   - `await tab.async_select()` — switches to the correct tab
   - `await session.async_activate()` — focuses the specific pane

3. **No behavior change for non-minimized windows.** Calling `window.async_activate()` on an already-visible window is a no-op (it just ensures focus). Same for `tab.async_select()` on the active tab.

### Testing

- **Unit tests:** Mock iTerm2 objects and verify all three activation calls (`window.async_activate()`, `tab.async_select()`, `session.async_activate()`) are made in order when a PID match is found.
- **Unit test:** Verify that when no match is found, no activation calls are made and `False` is returned.
- **Manual verification:** Minimize an iTerm2 window running a Claude session, press Enter in cctop, confirm the window un-minimizes and the correct pane is focused.

### Scope

- Only `src/cctop/sources/iterm2.py` is modified (the `activate_session` method)
- No changes to `session_list.py` or the notification logic
- No new dependencies
