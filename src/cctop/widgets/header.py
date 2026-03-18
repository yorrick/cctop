from rich.text import Text
from textual.widgets import Static

from cctop.models import Session

SORT_LABELS = ["idle time", "duration", "name", "status"]


class Header(Static):
    """Top bar showing session counts and current sort mode."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: list[Session] = []
        self._sort_index: int = 0

    def update_info(self, sessions: list[Session], sort_index: int) -> None:
        self._sessions = sessions
        self._sort_index = sort_index
        self.refresh()

    def render(self) -> Text:
        total = len(self._sessions)
        working = sum(1 for s in self._sessions if s.status == "working")
        idle = sum(1 for s in self._sessions if s.status == "idle")
        offline = sum(1 for s in self._sessions if s.status == "offline")

        line = Text()
        line.append("  cctop", style="bold white")
        line.append(f" — {total} session{'s' if total != 1 else ''}", style="white")
        line.append(" (", style="dim")
        if working:
            line.append(f"{working} working", style="green")
            if idle or offline:
                line.append(", ", style="dim")
        if idle:
            line.append(f"{idle} idle", style="yellow")
            if offline:
                line.append(", ", style="dim")
        if offline:
            line.append(f"{offline} offline", style="bright_black")
        line.append(")", style="dim")

        sort_label = SORT_LABELS[self._sort_index % len(SORT_LABELS)]
        padding = " " * max(1, 60 - len(line.plain))
        line.append(padding)
        line.append(f"Sort: [{sort_label} ▼]", style="dim")

        # Column headers
        line.append("\n")
        line.append("     ", style="dim")
        line.append(f"{'PROJECT':<24}", style="dim bold")
        line.append(f"{'NAME':<16}", style="dim bold")
        line.append(f"{'BRANCH':<22}", style="dim bold")
        line.append(f"{'STATUS':<20}", style="dim bold")
        line.append(f"{'MSGS':>4}", style="dim bold")
        line.append("  ", style="dim")
        line.append(f"{'DURATION':>8}", style="dim bold")
        line.append("  ", style="dim")
        line.append(f"{'IDLE':>6}", style="dim bold")

        return line
