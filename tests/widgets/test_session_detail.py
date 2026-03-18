from datetime import datetime, timezone
from pathlib import Path

from cctop.models import Session
from cctop.widgets.session_detail import SessionDetail

_DEFAULTS = dict(
    session_id="abc-123",
    pid=12345,
    cwd=Path("/tmp/test"),
    project_name="test",
    status="idle",
    started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    last_activity=datetime(2026, 1, 1, tzinfo=timezone.utc),
)


def test_session_detail_shows_session_id() -> None:
    session = Session(**{**_DEFAULTS, "session_id": "sess-abc-123"})  # type: ignore[arg-type]
    detail = SessionDetail(session)
    rendered = detail.render().plain
    assert "Session: sess-abc-123" in rendered


def test_session_detail_shows_directory() -> None:
    session = Session(**{**_DEFAULTS, "cwd": Path("/home/user/project")})  # type: ignore[arg-type]
    detail = SessionDetail(session)
    rendered = detail.render().plain
    assert "Dir: /home/user/project" in rendered


def test_session_detail_shows_pr_info() -> None:
    session = Session(
        **{**_DEFAULTS, "pr_title": "Fix bug", "pr_url": "https://github.com/org/repo/pull/1"},  # type: ignore[arg-type]
    )
    detail = SessionDetail(session)
    rendered = detail.render().plain
    assert "PR: Fix bug" in rendered
    assert "https://github.com/org/repo/pull/1" in rendered


def test_session_detail_shows_llm_summary_over_builtin() -> None:
    session = Session(**{**_DEFAULTS, "summary": "builtin summary"})  # type: ignore[arg-type]
    detail = SessionDetail(session, llm_summary="llm summary")
    rendered = detail.render().plain
    assert "llm summary" in rendered
    assert "builtin summary" not in rendered


def test_session_detail_shows_builtin_summary_when_no_llm() -> None:
    session = Session(**{**_DEFAULTS, "summary": "builtin summary"})  # type: ignore[arg-type]
    detail = SessionDetail(session)
    rendered = detail.render().plain
    assert "Summary: builtin summary" in rendered


def test_session_detail_shows_first_prompt_as_fallback() -> None:
    session = Session(**{**_DEFAULTS, "first_prompt": "hello world"})  # type: ignore[arg-type]
    detail = SessionDetail(session)
    rendered = detail.render().plain
    assert "Prompt: hello world" in rendered


def test_session_detail_shows_branch_and_message_count() -> None:
    session = Session(
        **{**_DEFAULTS, "git_branch": "feature/x", "message_count": 42},  # type: ignore[arg-type]
    )
    detail = SessionDetail(session)
    rendered = detail.render().plain
    assert "Branch: feature/x" in rendered
    assert "Messages: 42" in rendered
