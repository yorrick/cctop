import json
import os
import shutil
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any

from loguru import logger

HOOK_EVENTS = ["PreToolUse", "PostToolUse", "Stop", "SessionStart", "SessionEnd"]
MATCHER_EVENTS = {"PreToolUse", "PostToolUse"}


def install_hooks(
    cctop_dir: Path | None = None,
    settings_path: Path | None = None,
) -> None:
    """Install cctop hooks into Claude Code settings."""
    cctop_dir = cctop_dir or Path.home() / ".cctop"
    settings_path = settings_path or Path.home() / ".claude" / "settings.json"

    if not shutil.which("jq"):
        raise RuntimeError("jq is required for hooks. Install it with: brew install jq")

    hooks_dir = cctop_dir / "hooks"
    data_dir = cctop_dir / "data"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    hook_dest = hooks_dir / "cctop-hook.sh"
    hook_source = resources.files("cctop.hooks").joinpath("cctop-hook.sh")
    hook_dest.write_bytes(hook_source.read_bytes())
    hook_dest.chmod(0o755)

    settings = _load_settings(settings_path)
    hooks = settings.setdefault("hooks", {})
    hook_command = str(hook_dest)

    for event in HOOK_EVENTS:
        event_hooks = hooks.setdefault(event, [])
        if any(_has_cctop_hook(entry.get("hooks", [])) for entry in event_hooks if isinstance(entry, dict)):
            continue

        entry: dict[str, Any] = {
            "hooks": [{"type": "command", "command": hook_command, "timeout": 5}],
        }
        if event in MATCHER_EVENTS:
            entry["matcher"] = "*"

        event_hooks.append(entry)

    _atomic_write_json(settings_path, settings)
    logger.info("Hooks installed. Restart your Claude Code sessions for hooks to take effect.")


def uninstall_hooks(
    cctop_dir: Path | None = None,
    settings_path: Path | None = None,
) -> None:
    """Remove cctop hooks from Claude Code settings and clean up."""
    cctop_dir = cctop_dir or Path.home() / ".cctop"
    settings_path = settings_path or Path.home() / ".claude" / "settings.json"

    if settings_path.is_file():
        settings = _load_settings(settings_path)
        hooks = settings.get("hooks", {})

        for event in HOOK_EVENTS:
            if event not in hooks:
                continue

            remaining_hooks = [entry for entry in hooks[event] if not _has_cctop_hook(entry.get("hooks", []))]
            if remaining_hooks:
                hooks[event] = remaining_hooks
            else:
                del hooks[event]

        _atomic_write_json(settings_path, settings)

    if cctop_dir.exists():
        shutil.rmtree(cctop_dir)

    logger.info("cctop hooks removed and data cleaned up.")


def _load_settings(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text())
    return {}


def _has_cctop_hook(entries: list[dict[str, Any]] | list[Any]) -> bool:
    return any("cctop" in entry.get("command", "") for entry in entries if isinstance(entry, dict))


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON to a file atomically using a temp file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
            json.dump(data, file_obj, indent=2)
            file_obj.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
