import json
from pathlib import Path

from cctop.sources.summarize import strip_transcript


def _write_transcript(path: Path, messages: list[dict]) -> None:  # type: ignore[type-arg]
    path.write_text("\n".join(json.dumps(m) for m in messages) + "\n")


def test_strip_transcript_basic(tmp_path: Path) -> None:
    """Extracts user and assistant messages, skips system entries."""
    t = tmp_path / "sess.jsonl"
    _write_transcript(
        t,
        [
            {"type": "system", "content": "system stuff"},
            {"type": "user", "message": {"content": [{"type": "text", "text": "Hello Claude"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello!"}]}},
            {"type": "progress", "content": "ignored"},
        ],
    )
    result = strip_transcript(t)
    assert "Hello Claude" in result
    assert "Hello!" in result
    assert "system stuff" not in result
    assert "ignored" not in result


def test_strip_transcript_strips_system_tags(tmp_path: Path) -> None:
    """Removes <system-reminder> and similar tags from user messages."""
    t = tmp_path / "sess.jsonl"
    _write_transcript(
        t,
        [
            {
                "type": "user",
                "message": {
                    "content": [{"type": "text", "text": "<system-reminder>boilerplate</system-reminder>What is 2+2?"}]
                },
            },
        ],
    )
    result = strip_transcript(t)
    assert "boilerplate" not in result
    assert "What is 2+2?" in result


def test_strip_transcript_truncates_long_messages(tmp_path: Path) -> None:
    """Truncates individual messages to 500 chars."""
    t = tmp_path / "sess.jsonl"
    long_text = "x" * 1000
    _write_transcript(
        t,
        [
            {"type": "user", "message": {"content": [{"type": "text", "text": long_text}]}},
        ],
    )
    result = strip_transcript(t)
    # The user message content should be truncated
    assert len(result) < 600


def test_strip_transcript_first_last_three(tmp_path: Path) -> None:
    """Takes first 3 + last 3, adds omission separator for skipped middle."""
    t = tmp_path / "sess.jsonl"
    messages = []
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(
            {
                "type": role,
                "message": {"content": [{"type": "text", "text": f"message {i}"}]},
            }
        )
    _write_transcript(t, messages)
    result = strip_transcript(t)
    assert "message 0" in result
    assert "message 9" in result
    assert "omitted" in result
    # Middle messages should not appear
    assert "message 4" not in result


def test_strip_transcript_no_separator_when_few_messages(tmp_path: Path) -> None:
    """No separator when total messages <= 6."""
    t = tmp_path / "sess.jsonl"
    messages = [{"type": "user", "message": {"content": [{"type": "text", "text": f"msg {i}"}]}} for i in range(4)]
    _write_transcript(t, messages)
    result = strip_transcript(t)
    assert "omitted" not in result


def test_strip_transcript_under_3000_chars(tmp_path: Path) -> None:
    """Output stays under 3000 chars even with max content."""
    t = tmp_path / "sess.jsonl"
    messages = []
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append(
            {
                "type": role,
                "message": {"content": [{"type": "text", "text": "x" * 1000}]},
            }
        )
    _write_transcript(t, messages)
    result = strip_transcript(t)
    assert len(result) <= 3000


def test_strip_transcript_empty_file(tmp_path: Path) -> None:
    """Returns empty string for empty transcript."""
    t = tmp_path / "sess.jsonl"
    t.write_text("")
    result = strip_transcript(t)
    assert result == ""
