from rich.text import Text
from textual.widgets import Static


class Footer(Static):
    """Bottom bar showing keyboard shortcuts."""

    def render(self) -> Text:
        line = Text()
        shortcuts = [
            ("↑↓", "navigate"),
            ("Enter", "expand/collapse"),
            ("F6", "sort"),
            ("/", "filter"),
            ("?", "help"),
            ("q", "quit"),
        ]
        for key, action in shortcuts:
            line.append(f"  {key} ", style="bold")
            line.append(action, style="dim")
        return line
