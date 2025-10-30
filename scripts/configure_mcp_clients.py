#!/usr/bin/env python3
"""Configure MCP-aware clients (VS Code, Claude Desktop) for this project.

The script is conservative and cross-platform:

* Detects the repo's virtualenv Python (or accepts `--python` to override).
* Locates the VS Code user settings file (`settings.json`) and Claude Desktop
  configuration (`claude_desktop_config.json`) on macOS, Linux, and Windows.
* Creates timestamped backups before modifying any file.
* Allows add/update, remove, print, or skip actions for each client via CLI
  flags or interactive prompts.

Usage examples:

```
python scripts/configure_mcp_clients.py                 # interactive
python scripts/configure_mcp_clients.py --vscode-action print --claude-action print
python scripts/configure_mcp_clients.py --vscode-action update --claude-action remove \
    --python /custom/python
```
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ARGS = [str(REPO_ROOT / "src" / "mcp_server.py")]


# ---------------------------------------------------------------------------
# Utilities


def is_interactive() -> bool:
    return sys.stdin.isatty()


def detect_venv_python() -> Optional[Path]:
    candidates = [
        REPO_ROOT / ".venv" / "bin" / "python",
        REPO_ROOT / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def timestamped_backup(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".mcp-backup-{ts}")
    if path.exists():
        backup.write_text(path.read_text())
    return backup


def load_json(path: Path) -> Dict[str, object]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


def save_json(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamped_backup(path)
    try:
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
    except OSError as exc:
        raise RuntimeError(f"Unable to write {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# VS Code


def vscode_candidate_paths() -> list[Path]:
    home = Path.home()
    system = platform.system()

    names = ["Code", "Code - Insiders", "VSCodium"]

    candidates: list[Path] = []
    if system == "Darwin":
        for name in names:
            candidates.append(
                home / f"Library/Application Support/{name}/User/settings.json"
            )
    elif system == "Windows":
        appdata = home / "AppData/Roaming"
        for name in names:
            candidates.append(appdata / name / "User" / "settings.json")
    else:  # Linux / other Unix
        base_configs = [
            home / ".config",
            home / ".var/app/com.visualstudio.code/config",
            home / ".var/app/com.visualstudio.code.insiders/config",
            home / ".var/app/com.vscodium.codium/config",
        ]
        for base in base_configs:
            for name in names:
                candidates.append(base / name / "User" / "settings.json")

    # ensure unique order-preserving
    seen = set()
    unique: list[Path] = []
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    if not unique:
        raise RuntimeError(
            "Unable to determine VS Code settings location for this platform."
        )
    return unique


def select_vscode_settings(override: Optional[str]) -> Path:
    if override:
        return Path(override).expanduser()
    for candidate in vscode_candidate_paths():
        if candidate.exists():
            return candidate
    # fallback to first candidate and create parent dirs later
    return vscode_candidate_paths()[0]


def vscode_get_entry(data: Dict[str, object]) -> Optional[Dict[str, object]]:
    servers = data.get("mcp.servers")
    if isinstance(servers, dict):
        entry = servers.get("agentDebug")
        if isinstance(entry, dict):
            return entry
    return None


def vscode_update(data: Dict[str, object], python_path: Path) -> None:
    servers = data.setdefault("mcp.servers", {})
    if not isinstance(servers, dict):
        raise RuntimeError("Expected 'mcp.servers' to be an object in VS Code settings")
    servers["agentDebug"] = {
        "command": str(python_path),
        "args": SERVER_ARGS,
        "cwd": str(REPO_ROOT),
    }


def vscode_remove(data: Dict[str, object]) -> None:
    servers = data.get("mcp.servers")
    if isinstance(servers, dict) and "agentDebug" in servers:
        del servers["agentDebug"]
        if not servers:
            del data["mcp.servers"]


# ---------------------------------------------------------------------------
# Claude Desktop


def claude_candidate_paths() -> list[Path]:
    home = Path.home()
    system = platform.system()

    candidates: list[Path] = []
    if system == "Darwin":
        candidates.append(
            home / "Library/Application Support/Claude/claude_desktop_config.json"
        )
    elif system == "Windows":
        candidates.append(home / "AppData/Roaming/Claude/claude_desktop_config.json")
    else:
        candidates.extend(
            [
                home / ".config/Claude/claude_desktop_config.json",
                home / ".local/share/Claude/claude_desktop_config.json",
            ]
        )

    # ensure unique order-preserving
    seen = set()
    unique: list[Path] = []
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    if not unique:
        raise RuntimeError(
            "Unable to determine Claude Desktop configuration location for this platform."
        )
    return unique


def select_claude_config(override: Optional[str]) -> Path:
    if override:
        return Path(override).expanduser()
    for candidate in claude_candidate_paths():
        if candidate.exists():
            return candidate
    return claude_candidate_paths()[0]


def claude_get_entry(data: Dict[str, object]) -> Optional[Dict[str, object]]:
    servers = data.get("mcpServers")
    if isinstance(servers, dict):
        entry = servers.get("agentDebug")
        if isinstance(entry, dict):
            return entry
    return None


def claude_update(data: Dict[str, object], python_path: Path) -> None:
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise RuntimeError("Expected 'mcpServers' to be an object in Claude config")
    servers["agentDebug"] = {
        "command": str(python_path),
        "args": SERVER_ARGS,
        "cwd": str(REPO_ROOT),
        "env": {},
    }


def claude_remove(data: Dict[str, object]) -> None:
    servers = data.get("mcpServers")
    if isinstance(servers, dict) and "agentDebug" in servers:
        del servers["agentDebug"]
        if not servers:
            del data["mcpServers"]


# ---------------------------------------------------------------------------
# CLI helpers


def prompt_action(
    action: str, existing: Optional[Dict[str, object]], client: str
) -> str:
    if action != "prompt":
        return action

    if existing:
        print(f"[{client}] Current configuration:")
        print(json.dumps(existing, indent=2))
        prompt = "(U)pdate, (R)emove, or (S)kip? "
        default = "u"
        valid = {"u", "update", "r", "remove", "s", "skip"}
    else:
        prompt = "Add configuration now? (Y/n) "
        default = "y"
        valid = {"y", "yes", "n", "no"}

    if not is_interactive():
        choice = default
    else:
        while True:
            choice = input(prompt).strip().lower() or default
            if choice in valid:
                break
            print("Invalid choice. Please try again.")

    if existing:
        if choice.startswith("u"):
            return "update"
        if choice.startswith("r"):
            return "remove"
        return "skip"
    else:
        return "update" if choice.startswith("y") else "skip"


def ensure_python_path(path_arg: Optional[str]) -> Path:
    if path_arg:
        return Path(path_arg).expanduser()

    detected = detect_venv_python()
    if detected is None and not is_interactive():
        raise RuntimeError("No virtualenv Python detected; specify one with --python.")

    if detected is not None:
        if not is_interactive():
            print(f"Using detected Python at '{detected}'.")
            return detected
        choice = input(f"Use detected Python at '{detected}'? [Y/n] ").strip().lower()
        if choice in ("", "y", "yes"):
            return detected

    if not is_interactive():
        raise RuntimeError(
            "Non-interactive mode requires --python when auto-detection is declined."
        )

    while True:
        entered = input("Enter full path to Python executable: ").strip()
        path = Path(entered).expanduser()
        if not entered:
            print("Path cannot be empty.")
            continue
        if not path.exists():
            print("Path does not exist. Try again.")
            continue
        return path


def process_vscode(args, python_path: Path) -> None:
    if args.vscode_action == "skip":
        return
    settings_path = select_vscode_settings(args.vscode_settings)
    settings = load_json(settings_path)
    existing = vscode_get_entry(settings)
    action = prompt_action(args.vscode_action, existing, "VS Code")

    if action == "skip":
        print("[VS Code] Skipped.")
        return
    if action == "print":
        print("[VS Code] Current entry:")
        print(json.dumps(existing or {}, indent=2))
        return
    if action == "remove":
        if existing is None:
            print("[VS Code] No entry to remove.")
            return
        vscode_remove(settings)
        save_json(settings_path, settings)
        print(f"[VS Code] Removed agentDebug entry from {settings_path}")
        return

    # update
    vscode_update(settings, python_path)
    save_json(settings_path, settings)
    print(f"[VS Code] Updated agentDebug entry in {settings_path}")


def process_claude(args, python_path: Path) -> None:
    if args.claude_action == "skip":
        return
    config_path = select_claude_config(args.claude_config)
    config = load_json(config_path)
    existing = claude_get_entry(config)
    action = prompt_action(args.claude_action, existing, "Claude Desktop")

    if action == "skip":
        print("[Claude] Skipped.")
        return
    if action == "print":
        print("[Claude] Current entry:")
        print(json.dumps(existing or {}, indent=2))
        return
    if action == "remove":
        if existing is None:
            print("[Claude] No entry to remove.")
            return
        claude_remove(config)
        save_json(config_path, config)
        print(f"[Claude] Removed agentDebug entry from {config_path}")
        return

    claude_update(config, python_path)
    save_json(config_path, config)
    print(f"[Claude] Updated agentDebug entry in {config_path}")


# ---------------------------------------------------------------------------
# Entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", help="Path to Python executable for the MCP server")
    parser.add_argument("--vscode-settings", help="Override VS Code settings.json path")
    parser.add_argument("--claude-config", help="Override Claude Desktop config path")
    parser.add_argument(
        "--vscode-action",
        choices=["prompt", "update", "remove", "skip", "print"],
        default="prompt",
        help="Action to perform for VS Code configuration",
    )
    parser.add_argument(
        "--claude-action",
        choices=["prompt", "update", "remove", "skip", "print"],
        default="prompt",
        help="Action to perform for Claude Desktop configuration",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        python_path = ensure_python_path(args.python)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        process_vscode(args, python_path)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        process_claude(args, python_path)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
