from textual.binding import Binding
from textual.containers import VerticalScroll

from cctop.models import Session
from cctop.widgets.session_detail import SessionDetail
from cctop.widgets.session_row import SessionRow


class SessionList(VerticalScroll):
    """Scrollable list of sessions with expand/collapse."""

    BINDINGS = [
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("enter", "toggle_expand", "Expand/Collapse"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: list[Session] = []
        self._cursor: int = 0
        self._expanded: set[str] = set()

    def update_sessions(self, sessions: list[Session]) -> None:
        """Update the session list and re-render."""
        self._sessions = sessions
        if self._cursor >= len(sessions):
            self._cursor = max(0, len(sessions) - 1)
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild the widget tree."""
        self.remove_children()
        for i, session in enumerate(self._sessions):
            row = SessionRow(session, classes="cursor" if i == self._cursor else "")
            self.mount(row)
            if session.session_id in self._expanded:
                self.mount(SessionDetail(session))

    def action_cursor_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._rebuild()

    def action_cursor_down(self) -> None:
        if self._cursor < len(self._sessions) - 1:
            self._cursor += 1
            self._rebuild()

    def action_toggle_expand(self) -> None:
        if not self._sessions:
            return
        sid = self._sessions[self._cursor].session_id
        if sid in self._expanded:
            self._expanded.discard(sid)
        else:
            self._expanded.add(sid)
        self._rebuild()
