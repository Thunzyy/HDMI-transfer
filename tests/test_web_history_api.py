from __future__ import annotations

import pytest
from hdmi_transfer.adapters.history_store import HistoryStore


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HDMI_TRANSFER_STATE_DIR", str(tmp_path / "state"))
    from hdmi_transfer.interfaces.web.app_factory import create_app

    return create_app(output_dir=str(tmp_path / "out"), runtime=False)


def _complete(filename: str = "a.bin") -> dict:
    return {"protocol": "fountain", "filename": filename, "size": 4, "sha256_ok": True,
            "sha256_available": True, "duration_s": 2.0, "speed_mbps": 0.5,
            "save_path": "/out/" + filename}


def test_history_database_lives_in_state_dir(app, tmp_path) -> None:
    assert isinstance(app._history_store, HistoryStore)
    assert app._history_store.path == tmp_path / "state" / "history.sqlite3"


def test_get_history_lists_recorded_receptions(app) -> None:
    app._history_store.record_received(_complete(), timestamp_ms=10)
    response = app.test_client().get("/api/history")
    assert response.status_code == 200
    [item] = response.get_json()
    assert item["filename"] == "a.bin"
    assert item["duration"] == 2.0
    assert item["speed"] == 62_500.0


def test_delete_one_entry(app) -> None:
    entry_id = app._history_store.record_received(_complete(), timestamp_ms=10)
    client = app.test_client()
    assert client.delete(f"/api/history/{entry_id}").status_code == 200
    assert client.delete(f"/api/history/{entry_id}").status_code == 404
    assert client.get("/api/history").get_json() == []


def test_clear_history(app) -> None:
    app._history_store.record_received(_complete("a"), timestamp_ms=1)
    app._history_store.record_received(_complete("b"), timestamp_ms=2)
    response = app.test_client().delete("/api/history")
    assert response.get_json() == {"status": "cleared", "deleted": 2}


def test_import_browser_entries(app) -> None:
    client = app.test_client()
    entries = [{"type": "received", "filename": "x.zip", "timestamp": 99, "duration": 1.5,
                "speed": 1000, "success": True, "protocol": "fountain"}]
    first = client.post("/api/history/import", json={"entries": entries})
    again = client.post("/api/history/import", json={"entries": entries})
    assert first.get_json() == {"imported": 1}
    assert again.get_json() == {"imported": 0}
    assert client.post("/api/history/import", json={"entries": "nope"}).status_code == 400
