import shutil
from pathlib import Path
import uuid

import hdmi_transfer.interfaces.web.app_factory as app_factory
import hdmi_transfer.interfaces.web.routes_files as routes_files
import hdmi_transfer.web.server as server
import pytest


@pytest.fixture
def output_dir():
    root = Path(__file__).resolve().parent / ".tmp_file_api"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_receive_file_api_reports_and_deletes_output_file(output_dir, monkeypatch):
    monkeypatch.setattr(app_factory, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(output_dir), runtime=False)
    client = app.test_client()

    output_file = output_dir / "artifact.bin"
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


def test_receive_files_lists_output_directory_contents(output_dir, monkeypatch):
    monkeypatch.setattr(app_factory, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(output_dir), runtime=False)
    client = app.test_client()

    newer = output_dir / "b.bin"
    older = output_dir / "a.bin"
    older.write_bytes(b"aa")
    newer.write_bytes(b"bbb")

    listed = client.get("/api/receive/files")

    assert listed.status_code == 200
    assert listed.json == [
        {
            "filename": "a.bin",
            "modified_ms": int(older.stat().st_mtime * 1000),
            "size": 2,
            "system_path": str(older.resolve()),
        },
        {
            "filename": "b.bin",
            "modified_ms": int(newer.stat().st_mtime * 1000),
            "size": 3,
            "system_path": str(newer.resolve()),
        },
    ]


def test_receive_file_delete_missing_returns_404(output_dir, monkeypatch):
    monkeypatch.setattr(app_factory, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(output_dir), runtime=False)
    client = app.test_client()

    missing_path = Path(output_dir, "missing.bin").resolve()
    deleted = client.delete("/api/receive/file/missing.bin")

    assert deleted.status_code == 404
    assert deleted.json == {
        "error": "File not found",
        "exists": False,
        "filename": "missing.bin",
        "system_path": str(missing_path),
    }


def test_receive_file_reveal_existing_uses_file_manager_helper(output_dir, monkeypatch):
    monkeypatch.setattr(app_factory, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(output_dir), runtime=False)
    client = app.test_client()

    output_file = output_dir / "artifact.bin"
    output_file.write_bytes(b"hello")

    calls = []

    def fake_reveal(path):
        calls.append(path)
        return "file", str(Path(path).resolve())

    monkeypatch.setattr(routes_files, "_reveal_in_file_manager", fake_reveal)

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


def test_receive_file_reveal_missing_returns_404_when_no_location_exists(output_dir, monkeypatch):
    monkeypatch.setattr(app_factory, "_load_disk_cache", lambda: [])
    app = server.create_app(output_dir=str(output_dir), runtime=False)
    client = app.test_client()

    expected_path = Path(output_dir, "missing.bin").resolve()

    def fake_reveal(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(routes_files, "_reveal_in_file_manager", fake_reveal)

    response = client.post("/api/receive/file/missing.bin/reveal")

    assert response.status_code == 404
    assert response.json == {
        "error": "File location not found",
        "exists": False,
        "filename": "missing.bin",
        "system_path": str(expected_path),
    }


def test_reveal_in_file_manager_uses_windows_select_form(output_dir, monkeypatch):
    output_file = output_dir / "artifact.bin"
    output_file.write_bytes(b"hello")

    calls = []

    def fake_popen(args):
        calls.append(args)

    monkeypatch.setattr(routes_files.sys, "platform", "win32")
    monkeypatch.setattr(routes_files.subprocess, "Popen", fake_popen)

    opened, opened_path = routes_files._reveal_in_file_manager(str(output_file))

    assert (opened, opened_path) == ("file", str(output_file.resolve()))
    assert calls == [[
        "explorer.exe",
        "/select,",
        str(output_file.resolve()),
    ]]
