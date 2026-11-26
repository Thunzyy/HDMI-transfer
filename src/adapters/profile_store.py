"""Sender-PC profiles kept by the receiver.

A profile remembers the capture settings one sender PC needs, so switching
between PCs restores them. The store also keeps two receiver-wide values: the
active profile and the auto receive switch. Like the history, it is best effort:
a broken database logs a warning and never blocks a transfer.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from hdmi_transfer.core.config import PROFILES

log = logging.getLogger(__name__)

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        device_name TEXT,
        device_index INTEGER,
        profile TEXT NOT NULL,
        mode TEXT NOT NULL,
        bpc INTEGER NOT NULL,
        preview_quality INTEGER NOT NULL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS profiles_name ON profiles (name COLLATE NOCASE)",
    "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)",
)
_COLUMNS = (
    "id", "name", "device_name", "device_index", "profile", "mode", "bpc",
    "preview_quality", "created_at", "updated_at",
)
_EDITABLE = ("name", "device_name", "device_index", "profile", "mode", "bpc", "preview_quality")
_DEFAULTS = {"device_name": None, "device_index": None, "profile": "balanced",
             "mode": "fountain", "bpc": 2, "preview_quality": 45}
_MODES = ("fountain", "sequential", "auto")
_BPC = (1, 2, 3)
_PREVIEW_QUALITIES = (45, 60, 75, 90)
_LOCK = threading.Lock()


class ProfileError(ValueError):
    """A profile value is missing, invalid or already used."""


def default_profiles_path() -> Path:
    state_dir = Path(os.environ.get("HDMI_TRANSFER_STATE_DIR", Path.home() / ".hdmi-transfer"))
    return state_dir / "profiles.sqlite3"


def _int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ProfileError(f"Invalid {field}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ProfileError(f"Invalid {field}") from None


def _validated(data: dict) -> dict:
    name = str(data.get("name") or "").strip()
    if not name:
        raise ProfileError("A sender PC needs a name")
    if len(name) > 60:
        raise ProfileError("Name is longer than 60 characters")
    if data["profile"] not in PROFILES:
        raise ProfileError(f"Unknown profile: {data['profile']}")
    if data["mode"] not in _MODES:
        raise ProfileError(f"Unknown mode: {data['mode']}")
    bpc = _int(data["bpc"], "encoding")
    if bpc not in _BPC:
        raise ProfileError("Encoding must be 1, 2 or 3 bpc")
    preview = _int(data["preview_quality"], "preview quality")
    if preview not in _PREVIEW_QUALITIES:
        raise ProfileError("Unknown preview quality")
    device_name = data.get("device_name")
    device_index = data.get("device_index")
    return {
        "name": name,
        "device_name": str(device_name).strip() or None if device_name is not None else None,
        "device_index": None if device_index is None else _int(device_index, "device"),
        "profile": data["profile"], "mode": data["mode"], "bpc": bpc, "preview_quality": preview,
    }


class ProfileStore:
    """Sender-PC profiles and receiver state in one SQLite file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_profiles_path()

    # -- plumbing ---------------------------------------------------------

    def _run(self, operation, *, default=None, create: bool = False):
        try:
            with _LOCK:
                if not create and not self.path.exists():
                    return default
                self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self.path, timeout=5)
                try:
                    for statement in _SCHEMA:
                        connection.execute(statement)
                    with connection:
                        return operation(connection)
                finally:
                    connection.close()
        except (OSError, sqlite3.DatabaseError) as exc:
            if isinstance(exc, sqlite3.IntegrityError):
                raise ProfileError("A sender PC with this name already exists") from None
            log.warning("Sender profiles unavailable (%s): %s", self.path, exc)
            return default

    @staticmethod
    def _row(row) -> dict | None:
        return dict(zip(_COLUMNS, row)) if row else None

    @staticmethod
    def _select(connection, profile_id: int):
        return connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM profiles WHERE id = ?", (profile_id,),
        ).fetchone()

    def _get_state(self, key: str) -> str | None:
        row = self._run(lambda c: c.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone())
        return row[0] if row else None

    def _set_state(self, key: str, value: str | None) -> None:
        def operation(connection):
            if value is None:
                connection.execute("DELETE FROM state WHERE key = ?", (key,))
            else:
                connection.execute(
                    "INSERT INTO state (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value),
                )
        self._run(operation, create=True)

    # -- profiles ---------------------------------------------------------

    def list(self) -> list[dict]:
        rows = self._run(lambda c: c.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM profiles ORDER BY updated_at DESC, id DESC",
        ).fetchall(), default=[])
        return [self._row(row) for row in rows]

    def get(self, profile_id: int) -> dict | None:
        return self._row(self._run(lambda c: self._select(c, int(profile_id))))

    def create(self, data: dict) -> dict:
        values = _validated({**_DEFAULTS, **data})
        now = time.time()

        def operation(connection):
            cursor = connection.execute(
                "INSERT INTO profiles (name, device_name, device_index, profile, mode, bpc, "
                "preview_quality, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*(values[k] for k in _EDITABLE), now, now),
            )
            return self._select(connection, cursor.lastrowid)

        created = self._row(self._run(operation, create=True))
        if created is None:
            raise ProfileError("Sender profiles are unavailable")
        return created

    def update(self, profile_id: int, data: dict) -> dict | None:
        current = self.get(profile_id)
        if current is None:
            return None
        merged = {k: current[k] for k in _EDITABLE}
        merged.update({k: v for k, v in data.items() if k in _EDITABLE})
        values = _validated(merged)

        def operation(connection):
            connection.execute(
                "UPDATE profiles SET name = ?, device_name = ?, device_index = ?, profile = ?, "
                "mode = ?, bpc = ?, preview_quality = ?, updated_at = ? WHERE id = ?",
                (*(values[k] for k in _EDITABLE), time.time(), int(profile_id)),
            )
            return self._select(connection, int(profile_id))

        return self._row(self._run(operation, create=True))

    def delete(self, profile_id: int) -> bool:
        def operation(connection):
            deleted = connection.execute("DELETE FROM profiles WHERE id = ?", (int(profile_id),)).rowcount
            connection.execute(
                "DELETE FROM state WHERE key = 'active_profile_id' AND value = ?", (str(int(profile_id)),),
            )
            return deleted > 0
        return bool(self._run(operation, default=False))

    def matching_profile_ids(self, profile_id: int) -> list[int]:
        """Other profiles on the same capture device and transfer profile, newest first."""
        reference = self.get(profile_id)
        if reference is None:
            return []
        return [
            p["id"] for p in self.list()
            if p["id"] != reference["id"]
            and p["device_name"] == reference["device_name"]
            and p["profile"] == reference["profile"]
        ]

    # -- receiver state ---------------------------------------------------

    def get_active_id(self) -> int | None:
        value = self._get_state("active_profile_id")
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    def set_active_id(self, profile_id: int | None) -> None:
        if profile_id is None:
            self._set_state("active_profile_id", None)
            return
        if self.get(profile_id) is None:
            raise ProfileError("Unknown sender PC")
        self._set_state("active_profile_id", str(int(profile_id)))

    def get_auto_receive(self) -> bool:
        return self._get_state("auto_receive") == "1"

    def set_auto_receive(self, enabled: bool) -> None:
        self._set_state("auto_receive", "1" if enabled else "0")
