"""Configuration management for Claude Usage Tray.

Stores config in platform-appropriate location:
- macOS: ~/Library/Application Support/claude-usage-tray/config.json
- Linux: ~/.config/claude-usage-tray/config.json
- Windows: %APPDATA%/claude-usage-tray/config.json
"""

import json
import os
import stat
import sys
from pathlib import Path

APP_NAME = "claude-usage-tray"

DEFAULTS = {
    "session_cookie": "",
    "org_id": "",
    "refresh_interval": 5,
}


def get_config_dir() -> Path:
    """Return platform-specific config directory."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def load_config() -> dict:
    path = get_config_path()
    config = dict(DEFAULTS)
    if path.exists():
        try:
            with open(path, "r") as f:
                stored = json.load(f)
            config.update(stored)
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config: dict) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
    # Restrict permissions on Unix (contains session cookie)
    if sys.platform != "win32":
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def is_configured() -> bool:
    config = load_config()
    return bool(config.get("session_cookie")) and bool(config.get("org_id"))
