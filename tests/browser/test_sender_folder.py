"""Folder selection in the generated sender: folders are zipped before sending."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def browser():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    with webdriver.Chrome(options=options) as driver:
        yield driver


def _open_sender(browser):
    browser.get((ROOT / "sender.html").as_uri() + "?debugTitle=1")
    browser.execute_script("localStorage.clear()")


def _loaded_zip(browser) -> tuple[str, zipfile.ZipFile]:
    WebDriverWait(browser, 15).until(lambda d: d.find_element(By.ID, "startBtn").is_enabled())
    name = browser.find_element(By.ID, "fileName").text
    data = browser.execute_script("return Array.from(window.__senderPayload().bytes)")
    return name, zipfile.ZipFile(io.BytesIO(bytes(data)))


def test_folder_input_zips_whole_tree(browser, tmp_path):
    folder = tmp_path / "photos"
    (folder / "nested").mkdir(parents=True)
    (folder / "a.txt").write_bytes(b"alpha " * 500)
    (folder / "nested" / "b.bin").write_bytes(bytes(range(256)) * 8)

    _open_sender(browser)
    browser.find_element(By.ID, "folderInput").send_keys(str(folder))
    name, archive = _loaded_zip(browser)

    assert name == "photos.zip"
    assert archive.testzip() is None
    assert sorted(archive.namelist()) == ["photos/a.txt", "photos/nested/b.bin"]
    assert archive.read("photos/a.txt") == b"alpha " * 500
    assert archive.read("photos/nested/b.bin") == bytes(range(256)) * 8


def test_multiple_files_are_zipped(browser, tmp_path):
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_bytes(b"1")
    second.write_bytes("é".encode())

    _open_sender(browser)
    browser.find_element(By.ID, "fileInput").send_keys(f"{first}\n{second}")
    name, archive = _loaded_zip(browser)

    assert name == "files.zip"
    assert sorted(archive.namelist()) == ["one.txt", "two.txt"]
    assert archive.read("two.txt") == "é".encode()


def test_single_file_is_sent_unchanged(browser, tmp_path):
    payload = tmp_path / "single.txt"
    payload.write_bytes(b"plain")

    _open_sender(browser)
    browser.find_element(By.ID, "fileInput").send_keys(str(payload))
    WebDriverWait(browser, 15).until(lambda d: d.find_element(By.ID, "startBtn").is_enabled())

    assert browser.find_element(By.ID, "fileName").text == "single.txt"
    data = browser.execute_script("return Array.from(window.__senderPayload().bytes)")
    assert bytes(data) == b"plain"
