"""Optional iTerm2 integration for focus switching."""

from __future__ import annotations

from loguru import logger

# Lazy-loaded modules — set by connect() if available
_iterm2: object | None = None
_psutil: object | None = None


class ITermBridge:
    """Optional iTerm2 integration for focus switching.

    Connects to iTerm2's Python API on startup.  If the iterm2 or psutil
    packages are not installed, or if iTerm2's API server is not enabled,
    the bridge silently disables itself.
    """

    def __init__(self) -> None:
        self._connection: object | None = None
        self._available: bool = False

    @property
    def available(self) -> bool:
        """Whether iTerm2 integration is available."""
        return self._available

    async def connect(self) -> None:
        """Try to connect to iTerm2 API. Sets available=False on failure."""
        global _iterm2, _psutil  # noqa: PLW0603
        try:
            import iterm2
            import psutil

            _iterm2 = iterm2
            _psutil = psutil
        except ImportError:
            logger.debug("iterm2 or psutil not installed — iTerm2 integration disabled")
            return

        try:
            connection_cls = getattr(iterm2, "Connection")
            self._connection = await connection_cls.async_create()
            self._available = True
            logger.debug("Connected to iTerm2 API")
        except Exception as e:
            logger.debug("Failed to connect to iTerm2 API: {}", e)
            self._available = False

    async def activate_session(self, claude_pid: int) -> bool:
        """Focus the iTerm2 pane running the given Claude Code process.

        Walks up the process tree from claude_pid to find a matching
        iTerm2 session, then activates (focuses) it.

        Returns True if focused, False if no matching pane found.
        """
        if not self._available or _iterm2 is None or _psutil is None:
            return False

        try:
            app = await getattr(_iterm2, "async_get_app")(self._connection)

            # Build root-PID -> (window, tab, session) map
            pid_map: dict[int, tuple[object, object, object]] = {}
            for window in app.windows:
                for tab in window.tabs:
                    for session in tab.sessions:
                        root_pid = await session.async_get_variable("pid")
                        pid_map[root_pid] = (window, tab, session)

            # Walk up from Claude PID to find a match
            p = getattr(_psutil, "Process")(claude_pid)
            while p.pid > 1:
                if p.pid in pid_map:
                    window, tab, session = pid_map[p.pid]
                    # Activate window first (un-minimizes if needed), then tab, then pane
                    await getattr(window, "async_activate")()
                    await getattr(tab, "async_select")()
                    await getattr(session, "async_activate")()
                    logger.debug("Focused iTerm2 session for PID {}", claude_pid)
                    return True
                parent = p.parent()
                if parent is None:
                    break
                p = parent

            logger.debug("No iTerm2 session found for PID {}", claude_pid)
            return False

        except Exception as e:
            logger.debug("iTerm2 activate failed for PID {}: {}", claude_pid, e)
            return False
