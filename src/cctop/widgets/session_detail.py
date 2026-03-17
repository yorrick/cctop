from rich.text import Text
from textual.widgets import Static

from cctop.models import Session


class SessionDetail(Static):
    """Expanded detail view for a session."""

    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render(self) -> Text:
        s = self.session
        lines = Text()

        if s.pr_url and s.pr_title:
            lines.append(f"  │  PR: {s.pr_title}\n", style="blue")
            lines.append(f"  │  {s.pr_url}\n", style="dim blue")

        if s.summary:
            lines.append(f"  │  Summary: {s.summary}\n", style="white")

        if s.first_prompt:
            prompt = s.first_prompt[:120] + "..." if len(s.first_prompt) > 120 else s.first_prompt
            lines.append(f"  │  Prompt: {prompt}\n", style="dim")

        lines.append(f"  │  Dir: {s.cwd}\n", style="dim")

        if s.git_branch:
            lines.append(f"  │  Branch: {s.git_branch}", style="cyan")
            if s.message_count:
                lines.append(f"  Messages: {s.message_count}", style="dim")
            lines.append("\n")

        return lines
