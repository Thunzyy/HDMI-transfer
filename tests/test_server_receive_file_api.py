from pathlib import Path

import hdmi_exfil.web.server as server


def test_receive_file_api_reports_and_deletes_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(tmp_path))
    client = app.test_client()

    output_file = tmp_path / "artifact.bin"
    output_file.write_bytes(b"hello")

    info = client.get("/api/receive/file/artifact.bin")
    assert info.status_code == 200
    assert info.json == {
        "exists": True,
        "filename": "artifact.bin",
        "size": 5,
        "system_path": str(output_file.resolve()),
    }

    download = client.get("/api/receive/download/artifact.bin")
    assert download.status_code == 200
    assert download.data == b"hello"
    download.close()

    deleted = client.delete("/api/receive/file/artifact.bin")
    assert deleted.status_code == 200
    assert deleted.json == {
        "exists": False,
        "filename": "artifact.bin",
        "status": "deleted",
        "system_path": str(output_file.resolve()),
    }
    assert not output_file.exists()

    missing = client.get("/api/receive/file/artifact.bin")
    assert missing.status_code == 200
    assert missing.json == {
        "exists": False,
        "filename": "artifact.bin",
        "system_path": str(output_file.resolve()),
    }

    missing_download = client.get("/api/receive/download/artifact.bin")
    assert missing_download.status_code == 404


def test_receive_file_delete_missing_returns_404(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(tmp_path))
    client = app.test_client()

    missing_path = Path(tmp_path, "missing.bin").resolve()
    deleted = client.delete("/api/receive/file/missing.bin")

    assert deleted.status_code == 404
    assert deleted.json == {
        "error": "File not found",
        "exists": False,
        "filename": "missing.bin",
        "system_path": str(missing_path),
    }


def test_receive_file_reveal_existing_uses_file_manager_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(tmp_path))
    client = app.test_client()

    output_file = tmp_path / "artifact.bin"
    output_file.write_bytes(b"hello")

    calls = []

    def fake_reveal(path):
        calls.append(path)
        return "file", str(Path(path).resolve())

    monkeypatch.setattr(server, "_reveal_in_file_manager", fake_reveal)

    response = client.post("/api/receive/file/artifact.bin/reveal")

    assert response.status_code == 200
    assert response.json == {
        "exists": True,
        "filename": "artifact.bin",
        "opened": "file",
        "opened_path": str(output_file.resolve()),
        "status": "revealed",
        "system_path": str(output_file.resolve()),
    }
    assert calls == [str(output_file.resolve())]


def test_receive_file_reveal_missing_returns_404_when_no_location_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(tmp_path))
    client = app.test_client()

    expected_path = Path(tmp_path, "missing.bin").resolve()

    def fake_reveal(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(server, "_reveal_in_file_manager", fake_reveal)

    response = client.post("/api/receive/file/missing.bin/reveal")

    assert response.status_code == 404
    assert response.json == {
        "error": "File location not found",
        "exists": False,
        "filename": "missing.bin",
        "system_path": str(expected_path),
    }


def test_reveal_in_file_manager_uses_windows_select_form(tmp_path, monkeypatch):
    output_file = tmp_path / "artifact.bin"
    output_file.write_bytes(b"hello")

    calls = []

    def fake_popen(args):
        calls.append(args)

    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    opened, opened_path = server._reveal_in_file_manager(str(output_file))

    assert (opened, opened_path) == ("file", str(output_file.resolve()))
    assert calls == [[
        "explorer.exe",
        "/select,",
        str(output_file.resolve()),
    ]]
