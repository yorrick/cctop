import json
from pathlib import Path
from unittest.mock import patch

from cctop.hooks.install import install_hooks, uninstall_hooks


def test_install_creates_directories(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    claude_settings.write_text("{}")

    with patch("shutil.which", return_value="/usr/bin/jq"):
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    assert (cctop_dir / "hooks" / "cctop-hook.sh").is_file()
    assert (cctop_dir / "data").is_dir()


def test_install_appends_hooks_to_settings(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    claude_settings.write_text(
        json.dumps(
            {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "other-hook.sh"}]}]}}
        )
    )

    with patch("shutil.which", return_value="/usr/bin/jq"):
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    data = json.loads(claude_settings.read_text())
    pre_tool_hooks = data["hooks"]["PreToolUse"]
    assert len(pre_tool_hooks) == 2
    assert "other-hook.sh" in pre_tool_hooks[0]["hooks"][0]["command"]
    assert "cctop" in pre_tool_hooks[1]["hooks"][0]["command"]


def test_install_does_not_duplicate_hooks(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    claude_settings.write_text("{}")

    with patch("shutil.which", return_value="/usr/bin/jq"):
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)
        install_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    data = json.loads(claude_settings.read_text())
    assert len(data["hooks"]["PreToolUse"]) == 1


def test_uninstall_removes_only_cctop_hooks(tmp_path: Path) -> None:
    cctop_dir = tmp_path / ".cctop"
    claude_settings = tmp_path / "settings.json"
    settings_data = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "other-hook.sh"}]},
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": str(cctop_dir / "hooks" / "cctop-hook.sh")}],
                },
            ]
        }
    }
    claude_settings.write_text(json.dumps(settings_data))
    cctop_dir.mkdir(parents=True)

    uninstall_hooks(cctop_dir=cctop_dir, settings_path=claude_settings)

    data = json.loads(claude_settings.read_text())
    assert len(data["hooks"]["PreToolUse"]) == 1
    assert "other-hook.sh" in data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert not cctop_dir.exists()
