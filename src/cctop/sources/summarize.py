import asyncio
import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from loguru import logger

from cctop.sources.index import _SYSTEM_TAG_RE

_MAX_MSG_CHARS = 500
_MAX_TOTAL_CHARS = 3000
_KEEP_FIRST = 3
_KEEP_LAST = 3


def _extract_text(message: dict) -> str | None:  # type: ignore[type-arg]
    """Extract clean text content from a transcript message dict."""
    content = message.get("message", {}).get("content", "")
    if isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                text = _SYSTEM_TAG_RE.sub("", block["text"]).strip()
                if text:
                    return text
    elif isinstance(content, str):
        text = _SYSTEM_TAG_RE.sub("", content).strip()
        if text:
            return text
    return None


def strip_transcript(transcript_path: Path) -> str:
    """Read a JSONL transcript and return a compact text representation.

    Extracts only user/assistant messages, strips system tags, takes first 3
    + last 3 messages, truncates each to 500 chars. Target: under 3000 chars.
    """
    messages: list[tuple[str, str]] = []  # (role, text)

    try:
        with transcript_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type not in ("user", "assistant"):
                    continue

                text = _extract_text(data)
                if text:
                    messages.append((msg_type, text))
    except OSError:
        return ""

    if not messages:
        return ""

    # Select first 3 + last 3, with omission separator if needed
    if len(messages) <= _KEEP_FIRST + _KEEP_LAST:
        selected = messages
        omitted = 0
    else:
        first = messages[:_KEEP_FIRST]
        last = messages[-_KEEP_LAST:]
        omitted = len(messages) - _KEEP_FIRST - _KEEP_LAST
        selected = first + [("", "")] + last  # sentinel for separator

    parts: list[str] = []
    for role, text in selected:
        if role == "":
            parts.append(f"[... {omitted} messages omitted ...]")
            continue
        truncated = text[:_MAX_MSG_CHARS] + ("..." if len(text) > _MAX_MSG_CHARS else "")
        parts.append(f"{role.upper()}: {truncated}")

    result = "\n\n".join(parts)
    return result[:_MAX_TOTAL_CHARS]


async def generate_summary(transcript_path: Path) -> str | None:
    """Generate a 1-sentence summary of a session transcript via Claude Code SDK.

    Uses Claude Code subscription credentials (no ANTHROPIC_API_KEY needed).
    Returns None on any failure — callers should fall back to existing summary.
    """
    transcript = strip_transcript(transcript_path)
    if not transcript:
        logger.debug("No transcript content to summarize for {}", transcript_path)
        return None

    prompt = (
        "Summarize this Claude Code session in one short sentence (max 10 words).\n"
        "Focus on what the user is working on, not technical details.\n\n"
        f"Transcript:\n{transcript}"
    )

    try:
        result_text: str | None = None

        async def _run() -> str | None:
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=[],
                    model="claude-haiku-4-5",
                    max_turns=1,
                ),
            ):
                if isinstance(message, ResultMessage):
                    return message.result.strip() if message.result else None
            return None

        result_text = await asyncio.wait_for(_run(), timeout=30.0)
        if result_text:
            logger.debug("Generated summary for {}: {}", transcript_path.stem, result_text)
        return result_text
    except asyncio.TimeoutError:
        logger.warning("Summary generation timed out for {}", transcript_path.stem)
        return None
    except Exception as e:
        logger.warning("Summary generation failed for {}: {}", transcript_path.stem, e)
        return None
