"""SQLite transfer history kept by the receiver.

The receiver records every completed reception here so that duration and speed
survive browser changes, cleared caches and different hostnames. History is
best effort: a broken database never blocks a transfer.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL DEFAULT 'received',
    filename TEXT NOT NULL,
    size INTEGER,
    duration_s REAL,
    speed_bps REAL,
    success INTEGER,
    protocol TEXT,
    system_path TEXT,
    timestamp_ms INTEGER NOT NULL,
    UNIQUE (filename, timestamp_ms)
)
"""
_COLUMNS = "id, type, filename, size, duration_s, speed_bps, success, protocol, system_path, timestamp_ms"
_INSERT = (
    "INSERT OR IGNORE INTO transfers "
    "(type, filename, size, duration_s, speed_bps, success, protocol, system_path, timestamp_ms) "
    "VALUES ('received', ?, ?, ?, ?, ?, ?, ?, ?)"
)
_BYTES_PER_SECOND_PER_MBPS = 125_000
_LOCK = threading.Lock()


def default_history_path() -> Path:
    state_dir = Path(os.environ.get("HDMI_TRANSFER_STATE_DIR", Path.home() / ".hdmi-transfer"))
    return state_dir / "history.sqlite3"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _flag(value: object) -> int | None:
    return None if value is None else int(bool(value))


class HistoryStore:
    """Transfer history in one SQLite file, created on first write."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_history_path()

    def _connect(self, *, create: bool) -> sqlite3.Connection | None:
        if not create and not self.path.exists():
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute(_SCHEMA)
        return connection

    def _write(self, operation):
        try:
            with _LOCK:
                connection = self._connect(create=True)
                try:
                    with connection:
                        return operation(connection)
                finally:
                    connection.close()
        except (OSError, sqlite3.Error) as exc:
            log.warning("Transfer history unavailable (%s): %s", self.path, exc)
            return None

    def record_received(self, data: dict, *, timestamp_ms: int | None = None) -> int | None:
        """Store one ``complete`` receive event. Returns the row id."""
        speed_mbps = _number(data.get("speed_mbps"))
        row = (
            str(data.get("filename") or ""),
            _integer(data.get("size")),
            _number(data.get("duration_s")),
            speed_mbps * _BYTES_PER_SECOND_PER_MBPS if speed_mbps is not None else None,
            _flag(data.get("sha256_ok")),
            str(data.get("protocol") or "") or None,
            str(data.get("save_path") or "") or None,
            int(timestamp_ms if timestamp_ms is not None else time.time() * 1000),
        )
        if not row[0]:
            return None
        return self._write(lambda connection: connection.execute(_INSERT, row).lastrowid)

    def import_entries(self, entries: Iterable[object]) -> int:
        """Import received entries from the old browser history; duplicates are skipped."""
        rows = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "received":
                continue
            filename = entry.get("filename")
            timestamp = _integer(entry.get("timestamp"))
            if not isinstance(filename, str) or not filename or timestamp is None:
                continue
            rows.append((
                filename,
                _integer(entry.get("size")),
                _number(entry.get("duration")),
                _number(entry.get("speed")),
                _flag(entry.get("success")),
                str(entry.get("protocol") or "") or None,
                str(entry.get("systemPath") or "") or None,
                timestamp,
            ))
        if not rows:
            return 0

        def insert(connection: sqlite3.Connection) -> int:
            before = connection.total_changes
            connection.executemany(_INSERT, rows)
            return connection.total_changes - before

        return self._write(insert) or 0

    def list(self) -> list[dict]:
        try:
            with _LOCK:
                connection = self._connect(create=False)
                if connection is None:
                    return []
                try:
                    rows = connection.execute(
                        f"SELECT {_COLUMNS} FROM transfers ORDER BY timestamp_ms DESC, id DESC"
                    ).fetchall()
                finally:
                    connection.close()
        except (OSError, sqlite3.Error) as exc:
            log.warning("Transfer history unreadable (%s): %s", self.path, exc)
            return []
        return [
            {
                "id": row[0],
                "type": row[1],
                "filename": row[2],
                "size": row[3],
                "duration": row[4],
                "speed": row[5],
                "success": None if row[6] is None else bool(row[6]),
                "protocol": row[7],
                "systemPath": row[8] or "",
                "timestamp": row[9],
            }
            for row in rows
        ]

    def delete(self, entry_id: int) -> bool:
        deleted = self._write(
            lambda connection: connection.execute("DELETE FROM transfers WHERE id = ?", (entry_id,)).rowcount
        )
        return bool(deleted)

    def clear(self) -> int:
        return self._write(lambda connection: connection.execute("DELETE FROM transfers").rowcount) or 0
