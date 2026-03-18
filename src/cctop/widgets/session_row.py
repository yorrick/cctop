from datetime import timedelta

from rich.text import Text
from textual.widgets import Static

from cctop.models import Session

STATUS_ICONS = {
    "working": ("●", "green"),
    "idle": ("○", "yellow"),
    "offline": ("◌", "bright_black"),
}


def format_duration(td: timedelta) -> str:
    """Format a timedelta into a human-readable short string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "0s"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


class SessionRow(Static):
    """A single collapsed session row."""

    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render(self) -> Text:
        s = self.session
        icon, color = STATUS_ICONS.get(s.status, ("?", "white"))

        line = Text()
        line.append(f" {icon} ", style=color)
        name_display = s.name or "—"
        max_name_len = 16
        if len(name_display) > max_name_len:
            name_display = name_display[: max_name_len - 1] + "…"
        line.append(f"{name_display:<{max_name_len}}", style=None if s.name else "dim")
        line.append(f"{s.project_name:<24}", style="bold")

        branch_display = s.worktree_name or s.git_branch or "—"
        max_branch_len = 22
        if len(branch_display) > max_branch_len:
            branch_display = branch_display[: max_branch_len - 1] + "…"
        line.append(f"{branch_display:<{max_branch_len}}", style="cyan")

        if s.status == "working" and s.current_tool:
            line.append(f"Working: {s.current_tool:<10}", style="green")
        elif s.status == "idle":
            line.append(f"{'Idle':<20}", style="yellow")
        else:
            line.append(f"{'Offline':<20}", style="bright_black")

        msgs = str(s.message_count) if s.message_count else "—"
        line.append(f"{msgs:>4}", style="dim")
        line.append("  ", style="white")

        line.append(f"{format_duration(s.session_duration):>8}", style="white")
        line.append("  ", style="white")

        if s.status == "offline":
            line.append(f"{'—':>6}", style="bright_black")
        else:
            line.append(f"{format_duration(s.idle_duration):>6}", style="white")

        return line
