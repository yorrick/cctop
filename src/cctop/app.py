from datetime import timedelta
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches

from cctop.models import Session
from cctop.sources.events import EventsTailer
from cctop.sources.merger import SessionManager
from cctop.widgets.footer import Footer
from cctop.widgets.header import Header
from cctop.widgets.session_list import SessionList

SORT_KEYS: list[tuple[str, bool]] = [
    ("idle_duration", True),  # longest idle first
    ("session_duration", True),  # longest duration first
    ("project_name", False),  # alphabetical
    ("status", False),  # working -> idle -> offline
]

STATUS_ORDER = {"working": 0, "idle": 1, "offline": 2}


class CctopApp(App):
    """Main cctop Textual application."""

    TITLE = "cctop"
    CSS = """
    Header {
        height: 2;
        background: $surface;
    }
    Footer {
        height: 1;
        background: $surface;
        dock: bottom;
    }
    SessionList {
        height: 1fr;
    }
    .cursor {
        background: $accent 30%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f10", "quit", "Quit", show=False),
        Binding("f6", "cycle_sort", "Sort"),
        Binding("greater_than", "cycle_sort", "Sort", show=False),
        Binding("less_than", "cycle_sort_reverse", "Sort reverse", show=False),
        Binding("slash", "toggle_filter", "Filter"),
        Binding("question_mark", "show_help", "Help"),
        Binding("h", "show_help", "Help", show=False),
    ]

    def __init__(self, recent: timedelta = timedelta(0), **kwargs) -> None:
        super().__init__(**kwargs)
        self._manager = SessionManager(recent=recent)
        self._tailer = EventsTailer(Path.home() / ".cctop" / "data" / "events.jsonl")
        self._sort_index = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield SessionList(projects_dir=self._manager.projects_dir)
        yield Footer()

    async def on_mount(self) -> None:
        self._tailer.cleanup_if_needed()
        if not self._tailer.hooks_installed:
            self.notify(
                "Hooks not installed — run 'cctop install' for real-time status.",
                severity="warning",
                timeout=10,
            )
        self.set_interval(2, self._poll_fast)
        self.set_interval(10, self._poll_slow)
        self._poll_fast()
        await self._poll_slow()

    def _poll_fast(self) -> None:
        """Fast polling: session discovery, PID liveness, events."""
        self._manager.refresh()
        events = self._tailer.read_new()
        if events:
            self._manager.apply_events(events)
        self._update_ui()

    async def _poll_slow(self) -> None:
        """Slow polling: sessions-index refresh, PR lookups."""
        # Index data is refreshed in manager.refresh() already
        # PR lookups for sessions with a branch but no cached PR
        from cctop.sources.github import lookup_pr

        for session in self._manager.sessions:
            if session.git_branch and not session.pr_url:
                info = await lookup_pr(session.git_branch, str(session.cwd))
                if info:
                    session.pr_url = info.url
                    session.pr_title = info.title
        self._update_ui()

    def _sort_sessions(self, sessions: list[Session]) -> list[Session]:
        key_name, reverse = SORT_KEYS[self._sort_index % len(SORT_KEYS)]
        if key_name == "status":
            return sorted(sessions, key=lambda s: STATUS_ORDER.get(s.status, 9), reverse=reverse)
        return sorted(sessions, key=lambda s: getattr(s, key_name), reverse=reverse)

    def _update_ui(self) -> None:
        sessions = self._sort_sessions(self._manager.sessions)
        try:
            self.query_one(Header).update_info(sessions, self._sort_index)
            self.query_one(SessionList).update_sessions(sessions)
        except NoMatches:
            pass

    def action_cycle_sort(self) -> None:
        self._sort_index = (self._sort_index + 1) % len(SORT_KEYS)
        self._update_ui()

    def action_cycle_sort_reverse(self) -> None:
        self._sort_index = (self._sort_index - 1) % len(SORT_KEYS)
        self._update_ui()

    def action_toggle_filter(self) -> None:
        """Toggle filter input. Simple substring filter on project name."""
        self.notify("Filter: not yet implemented (planned for v0.2)", severity="information", timeout=3)

    def action_show_help(self) -> None:
        """Show help screen with keybindings."""
        help_text = (
            "cctop — Claude Code session monitor\n\n"
            "↑/↓ or k/j   Navigate sessions\n"
            "Enter         Expand / collapse\n"
            "c             Copy session ID\n"
            "F6 or >/<     Cycle sort mode\n"
            "/             Filter (coming soon)\n"
            "?/h           This help\n"
            "q / F10       Quit"
        )
        self.notify(help_text, severity="information", timeout=15)
