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
