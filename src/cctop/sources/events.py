import json
import time
from pathlib import Path

from loguru import logger

from cctop.models import Event

MAX_EVENTS_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_EVENT_AGE_SECONDS = 86400  # 24 hours


class EventsTailer:
    """Tails ~/.cctop/data/events.jsonl, tracking byte offset between reads."""

    def __init__(self, events_file: Path) -> None:
        self._path = events_file
        self._offset: int = 0

    @property
    def hooks_installed(self) -> bool:
        """Check if the events file directory exists (proxy for hooks being installed)."""
        return self._path.parent.is_dir()

    def cleanup_if_needed(self) -> None:
        """Truncate old events if file exceeds size limit."""
        if not self._path.is_file():
            return

        try:
            if self._path.stat().st_size <= MAX_EVENTS_FILE_SIZE:
                return

            cutoff = (time.time() - MAX_EVENT_AGE_SECONDS) * 1000  # ms
            kept_lines: list[str] = []
            with self._path.open() as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("ts", 0) >= cutoff:
                            kept_lines.append(line)
                    except json.JSONDecodeError:
                        pass

            self._path.write_text("".join(kept_lines))
            self._offset = 0
            logger.info("Cleaned up events.jsonl: kept {} recent events", len(kept_lines))
        except OSError as e:
            logger.warning("Failed to clean up events file: {}", e)

    def read_new(self) -> list[Event]:
        """Read any new events since the last call."""
        if not self._path.is_file():
            return []

        events: list[Event] = []
        try:
            with self._path.open() as f:
                f.seek(self._offset)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        events.append(Event.model_validate(data))
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning("Skipping malformed event line: {}", e)
                self._offset = f.tell()
        except OSError as e:
            logger.warning("Failed to read events file: {}", e)

        return events
