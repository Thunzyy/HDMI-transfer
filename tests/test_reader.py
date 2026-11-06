from __future__ import annotations

import io
import zipfile

from hdmi_transfer.core.file_handling.reader import read_input


def test_file_is_read_unchanged(tmp_path):
    payload = tmp_path / "data.bin"
    payload.write_bytes(b"raw")

    assert read_input(str(payload)) == ("data.bin", b"raw")


def test_directory_is_zipped_in_memory(tmp_path, monkeypatch):
    folder = tmp_path / "project"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "empty").mkdir()
    (folder / "a.txt").write_bytes(b"alpha")
    (folder / "sub" / "b.txt").write_bytes(b"beta")
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    name, data = read_input(str(folder) + "/")

    assert name == "project.zip"
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert archive.testzip() is None
    assert sorted(archive.namelist()) == [
        "project/a.txt",
        "project/sub/",
        "project/sub/b.txt",
        "project/sub/empty/",
    ]
    assert archive.read("project/sub/b.txt") == b"beta"
    assert list(workdir.iterdir()) == []
