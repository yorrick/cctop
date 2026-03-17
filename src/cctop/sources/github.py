import asyncio
import json

from loguru import logger
from pydantic import BaseModel


class PRInfo(BaseModel):
    """GitHub PR info for a branch."""

    url: str
    title: str


_cache: dict[str, PRInfo | None] = {}


async def lookup_pr(branch: str, cwd: str) -> PRInfo | None:
    """Look up a PR for a git branch using `gh`. Results are cached."""
    if branch in _cache:
        return _cache[branch]

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--json",
            "url,title",
            "--limit",
            "1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode != 0:
            _cache[branch] = None
            return None

        prs = json.loads(stdout.decode())
        if prs:
            info = PRInfo(url=prs[0]["url"], title=prs[0]["title"])
            _cache[branch] = info
            return info

        _cache[branch] = None
    except (FileNotFoundError, asyncio.TimeoutError, json.JSONDecodeError, KeyError) as e:
        logger.debug("PR lookup failed for branch {}: {}", branch, e)
        _cache[branch] = None

    return None


def clear_cache() -> None:
    """Clear the PR cache."""
    _cache.clear()
