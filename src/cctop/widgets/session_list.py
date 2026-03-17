from pathlib import Path

from loguru import logger
from textual.binding import Binding
from textual.containers import VerticalScroll

from cctop.models import Session
from cctop.sources.index import find_transcript_path
from cctop.sources.summarize import generate_summary
from cctop.widgets.session_detail import SessionDetail
from cctop.widgets.session_row import SessionRow

_GENERATING = "Generating..."


class SessionList(VerticalScroll):
    """Scrollable list of sessions with expand/collapse and LLM summaries."""

    BINDINGS = [
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("enter", "toggle_expand", "Expand/Collapse"),
        Binding("r", "regenerate_summary", "Regenerate summary", show=False),
    ]

    def __init__(self, projects_dir: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions: list[Session] = []
        self._cursor: int = 0
        self._expanded: set[str] = set()
        self._llm_summaries: dict[str, str] = {}
        self._projects_dir = projects_dir or Path.home() / ".claude" / "projects"

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
                llm_summary = self._llm_summaries.get(session.session_id)
                self.mount(SessionDetail(session, llm_summary=llm_summary))

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
        session = self._sessions[self._cursor]
        sid = session.session_id
        if sid in self._expanded:
            self._expanded.discard(sid)
            self._rebuild()
        else:
            self._expanded.add(sid)
            if sid not in self._llm_summaries:
                self._start_summary_generation(session)
            else:
                self._rebuild()

    def action_regenerate_summary(self) -> None:
        """Regenerate the LLM summary for the currently expanded session."""
        if not self._sessions:
            return
        session = self._sessions[self._cursor]
        sid = session.session_id
        # Guard: only act if this session is expanded
        if sid not in self._expanded:
            return
        self._llm_summaries.pop(sid, None)
        self._start_summary_generation(session)

    def _start_summary_generation(self, session: Session) -> None:
        """Set the generating sentinel, rebuild, then fire the worker."""
        sid = session.session_id
        self._llm_summaries[sid] = _GENERATING
        self._rebuild()
        self.run_worker(self._generate_and_apply(session), exit_on_error=False)

    async def _generate_and_apply(self, session: Session) -> None:
        """Background worker: find transcript, call Claude, update cache."""
        sid = session.session_id
        transcript_path = find_transcript_path(
            self._projects_dir,
            session.cwd,
            session.session_id,
            session.started_at,
        )
        if transcript_path is None:
            logger.warning("No transcript found for session {}", sid)
            self._llm_summaries.pop(sid, None)
            self._rebuild()
            return

        summary = await generate_summary(transcript_path)
        if summary:
            self._llm_summaries[sid] = summary
        else:
            logger.warning("Summary generation failed for session {}", sid)
            self._llm_summaries.pop(sid, None)
        self._rebuild()
