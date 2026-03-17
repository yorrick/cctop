import json
from unittest.mock import AsyncMock, patch

import pytest

from cctop.sources.github import clear_cache, lookup_pr


@pytest.fixture(autouse=True)
def _clear_pr_cache() -> None:
    clear_cache()


@pytest.mark.asyncio
async def test_lookup_pr_success() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        json.dumps([{"url": "https://github.com/org/repo/pull/42", "title": "Fix bug"}]).encode(),
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await lookup_pr("feat/fix-bug", "/tmp")

    assert result is not None
    assert result.url == "https://github.com/org/repo/pull/42"
    assert result.title == "Fix bug"


@pytest.mark.asyncio
async def test_lookup_pr_no_prs() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"[]", b"")
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await lookup_pr("no-pr-branch", "/tmp")

    assert result is None


@pytest.mark.asyncio
async def test_lookup_pr_gh_not_found() -> None:
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        result = await lookup_pr("any-branch", "/tmp")

    assert result is None


@pytest.mark.asyncio
async def test_lookup_pr_cache_hit() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        json.dumps([{"url": "https://example.com/pr/1", "title": "PR"}]).encode(),
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await lookup_pr("cached-branch", "/tmp")
        await lookup_pr("cached-branch", "/tmp")

    assert mock_exec.call_count == 1


@pytest.mark.asyncio
async def test_lookup_pr_gh_error_returns_none() -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"error")
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await lookup_pr("error-branch", "/tmp")

    assert result is None
