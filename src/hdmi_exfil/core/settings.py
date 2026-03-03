"""Persistent user settings stored in ~/.hdmi-exfil/settings.json.

Provides load/save/get/set for sender and receiver defaults so users
don't have to re-select capture device, monitor, profile, etc. every time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SETTINGS_DIR = Path.home() / ".hdmi-exfil"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"

_DEFAULTS: dict[str, Any] = {
    "sender": {
        "monitor": None,
        "profile": "speed",
        "mode": "sequential",
    },
    "receiver": {
        "device_name": None,
        "device_index": None,
        "profile": "speed",
        "mode": "auto",
        "output": "received_files",
    },
}


def _ensure_dir() -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict[str, Any]:
    """Load settings from disk, merging with defaults for missing keys."""
    settings = json.loads(json.dumps(_DEFAULTS))  # deep copy
    if _SETTINGS_FILE.exists():
        try:
            saved = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            for section in ("sender", "receiver"):
                if section in saved and isinstance(saved[section], dict):
                    settings[section].update(saved[section])
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save(settings: dict[str, Any]) -> None:
    """Write settings to disk."""
    _ensure_dir()
    _SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def get(section: str, key: str) -> Any:
    """Get a single setting value (returns default if unset)."""
    return load().get(section, {}).get(key)


def set_value(section: str, key: str, value: Any) -> None:
    """Set a single setting value and save."""
    settings = load()
    if section not in settings:
        settings[section] = {}
    settings[section][key] = value
    save(settings)


def settings_path() -> Path:
    """Return the path to the settings file."""
    return _SETTINGS_FILE
