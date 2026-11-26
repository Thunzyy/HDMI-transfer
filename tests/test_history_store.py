from __future__ import annotations

import sqlite3

from hdmi_transfer.adapters.history_store import HistoryStore


def _complete(**overrides) -> dict:
    data = {
        "protocol": "fountain",
        "filename": "report.pdf",
        "size": 2_000_000,
        "sha256_ok": True,
        "sha256_available": True,
        "duration_s": 12.5,
        "speed_mbps": 1.28,
        "save_path": "C:/received_files/report.pdf",
    }
    data.update(overrides)
    return data


def test_store_creates_database_lazily(tmp_path) -> None:
    path = tmp_path / "state" / "history.sqlite3"
    store = HistoryStore(path)
    assert not path.exists()
    assert store.list() == []
    store.record_received(_complete(), timestamp_ms=1_000)
    assert path.is_file()


def test_record_received_keeps_duration_and_speed(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    entry_id = store.record_received(_complete(), timestamp_ms=1_700_000_000_000)

    [item] = store.list()
    assert item == {
        "id": entry_id,
        "type": "received",
        "filename": "report.pdf",
        "size": 2_000_000,
        "duration": 12.5,
        "speed": 160_000.0,  # 1.28 Mbps in bytes per second
        "success": True,
        "protocol": "fountain",
        "systemPath": "C:/received_files/report.pdf",
        "timestamp": 1_700_000_000_000,
    }


def test_history_survives_a_new_store_instance(tmp_path) -> None:
    path = tmp_path / "history.sqlite3"
    HistoryStore(path).record_received(_complete(), timestamp_ms=5)
    assert [item["filename"] for item in HistoryStore(path).list()] == ["report.pdf"]


def test_list_returns_newest_first(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.record_received(_complete(filename="old.bin"), timestamp_ms=1)
    store.record_received(_complete(filename="new.bin"), timestamp_ms=2)
    assert [item["filename"] for item in store.list()] == ["new.bin", "old.bin"]


def test_failed_checksum_is_recorded_as_failure(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.record_received(_complete(sha256_ok=False), timestamp_ms=1)
    assert store.list()[0]["success"] is False


def test_delete_and_clear(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    first = store.record_received(_complete(filename="a"), timestamp_ms=1)
    store.record_received(_complete(filename="b"), timestamp_ms=2)
    store.record_received(_complete(filename="c"), timestamp_ms=3)

    assert store.delete(first) is True
    assert store.delete(first) is False
    assert [item["filename"] for item in store.list()] == ["c", "b"]
    assert store.clear() == 2
    assert store.list() == []


def test_import_browser_entries_is_idempotent(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    browser_entries = [
        {"type": "received", "filename": "clip.mp4", "size": 10, "duration": 3.2,
         "speed": 4096, "success": True, "timestamp": 1_000, "protocol": "sequential",
         "systemPath": "/data/clip.mp4"},
        {"type": "sent", "filename": "ignored.txt", "timestamp": 2_000},
        {"type": "received", "filename": "", "timestamp": 3_000},
        {"type": "received", "filename": "no-timestamp.bin"},
        "not a dict",
    ]

    assert store.import_entries(browser_entries) == 1
    assert store.import_entries(browser_entries) == 0
    [item] = store.list()
    assert item["filename"] == "clip.mp4"
    assert item["duration"] == 3.2
    assert item["speed"] == 4096
    assert item["systemPath"] == "/data/clip.mp4"


def test_unreadable_database_does_not_raise(tmp_path) -> None:
    path = tmp_path / "history.sqlite3"
    path.write_bytes(b"this is not sqlite")
    store = HistoryStore(path)
    assert store.list() == []
    assert store.record_received(_complete(), timestamp_ms=1) is None


def test_schema_uses_unique_filename_timestamp(tmp_path) -> None:
    path = tmp_path / "history.sqlite3"
    store = HistoryStore(path)
    store.record_received(_complete(), timestamp_ms=1)
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "transfers" in tables
