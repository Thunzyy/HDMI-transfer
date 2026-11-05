"""Persistent user settings stored in ~/.hdmi-transfer/settings.json.

Provides load/save/get/set for sender and receiver defaults so users
don't have to re-select capture device, monitor, profile, etc. every time.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from hdmi_transfer.domain.transfer_defaults import (
    DEFAULT_BITS_PER_CHANNEL,
    DEFAULT_MODE,
    DEFAULT_PROFILE_NAME,
)

_SETTINGS_DIR = Path(os.environ.get("HDMI_TRANSFER_STATE_DIR", Path.home() / ".hdmi-transfer"))
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"

_DEFAULTS: dict[str, Any] = {
    "sender": {
        "monitor": None,
        "profile": DEFAULT_PROFILE_NAME,
        "mode": DEFAULT_MODE,
        "bpc": DEFAULT_BITS_PER_CHANNEL,
    },
    "receiver": {
        "device_name": None,
        "device_index": None,
        "profile": DEFAULT_PROFILE_NAME,
        "mode": DEFAULT_MODE,
        "bpc": DEFAULT_BITS_PER_CHANNEL,
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
            if not isinstance(saved, dict):
                return settings
            for section in ("sender", "receiver"):
                if section in saved and isinstance(saved[section], dict):
                    settings[section].update(saved[section])
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save(settings: dict[str, Any]) -> None:
    """Atomically replace settings so an interrupted save cannot truncate them."""
    _ensure_dir()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=_SETTINGS_DIR, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        os.replace(temporary, _SETTINGS_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
