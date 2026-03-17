import asyncio
import json
from pathlib import Path

import anthropic
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
    """Generate a 1-sentence summary of a session transcript via Claude API.

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
        client = anthropic.AsyncAnthropic()
        response = await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=10.0,
        )
        block = response.content[0]
        if not isinstance(block, anthropic.types.TextBlock):
            return None
        text = block.text.strip()
        logger.debug("Generated summary for {}: {}", transcript_path.stem, text)
        return text
    except anthropic.AuthenticationError as e:
        logger.warning("Anthropic auth failed — Claude subscription required: {}", e)
        return None
    except anthropic.APIError as e:
        logger.warning("Anthropic API error for {}: {}", transcript_path.stem, e)
        return None
    except asyncio.TimeoutError:
        logger.warning("Summary generation timed out for {}", transcript_path.stem)
        return None
