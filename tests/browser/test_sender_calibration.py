"""Real generated sender in Chrome; no capture device or receiver API needed."""
from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from hdmi_transfer.application.preflight import build_calibration_payload, is_preflight_start_result
from hdmi_transfer.core.capture.sampler import sample_frame
from hdmi_transfer.core.config import PROFILES
from hdmi_transfer.core.protocols import get_protocol

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def browser():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    with webdriver.Chrome(options=options) as driver:
        yield driver


def prepare(browser, tmp_path, *, connected=False):
    browser.set_window_size(1920, 1080)
    query = "?debugTitle=1&fountainAutoStop=0"
    if connected:
        query += "&receiverApi=1&apiBaseUrl=http://127.0.0.1:59999"
    browser.get((ROOT / "sender.html").as_uri() + query)
    browser.execute_script("localStorage.clear()")
    browser.refresh()
    browser.execute_script("""
      document.documentElement.requestFullscreen = () => Promise.resolve();
      window.fetchCalls = 0;
      window.receiverState = {active:true, preflight_required:true, preflight_state:'waiting'};
      window.fetch = async () => {
        window.fetchCalls++;
        return {ok:true, json:async () => window.receiverState};
      };
    """)
    payload = tmp_path / "test.txt"
    payload.write_bytes(b"Calibration before data. " * 1000)
    browser.find_element(By.ID, "fileInput").send_keys(str(payload))
    WebDriverWait(browser, 10).until(lambda d: d.find_element(By.ID, "startBtn").is_enabled())
    return WebDriverWait(browser, 12)


def label(browser):
    return browser.execute_script("return document.getElementById('statusLabel').textContent")


def stop(browser):
    browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)


def test_offline_first_confirmation_saved_recheck_and_forced_calibration(browser, tmp_path):
    wait = prepare(browser, tmp_path)
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: label(d) == "Receiver ready? Press Enter")
    assert "[PREFLIGHT]" in browser.title
    assert " f=0 " in browser.title
    assert browser.execute_script("return window.fetchCalls") == 0

    # Decode actual canvas pixels, proving the generated JS agrees with Python.
    png = browser.execute_script("return document.getElementById('canvas').toDataURL().split(',')[1]")
    frame = cv2.imdecode(np.frombuffer(base64.b64decode(png), dtype=np.uint8), cv2.IMREAD_COLOR)
    profile = replace(PROFILES["balanced"], bits_per_channel=2)
    decoded = get_protocol("sequential", profile=profile).decode_frame(
        sample_frame(frame, profile.rows, profile.cols, profile.block_size))
    assert is_preflight_start_result(decoded)
    assert decoded.frame_index > 1
    assert decoded.data == build_calibration_payload(profile.seq_bytes_per_frame)

    browser.find_element(By.TAG_NAME, "body").send_keys(Keys.ENTER)
    wait.until(lambda d: label(d) == "Transmitting")
    stop(browser)
    assert label(browser) == "Stopped"
    assert browser.execute_script("return localStorage.getItem('hdmi_transfer_calibration_v1')")
    browser.find_element(By.ID, "startBtn").click()
    # A confirmed setup proceeds without a second Enter press.
    wait.until(lambda d: label(d) == "Transmitting")
    stop(browser)
    browser.set_window_size(1600, 900)
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: label(d) == "Receiver ready? Press Enter")
    assert " f=0 " in browser.title
    stop(browser)
    browser.set_window_size(1920, 1080)
    browser.find_element(By.ID, "recalibrateBtn").click()
    assert browser.execute_script("return localStorage.getItem('hdmi_transfer_calibration_v1')") is None
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: label(d) == "Receiver ready? Press Enter")
    assert " f=0 " in browser.title
    stop(browser)
    assert not [e for e in browser.get_log("browser") if e["level"] == "SEVERE"]


def test_connected_waits_for_fresh_receiver_confirmation(browser, tmp_path):
    wait = prepare(browser, tmp_path, connected=True)
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: "[PREFLIGHT]" in d.title)
    assert " f=0 " in browser.title
    browser.execute_script("window.receiverState = {active:true, preflight_required:true, preflight_state:'ok', transfer_bpc:2}")
    wait.until(lambda d: label(d) == "Transmitting")
    stop(browser)


def test_connected_rejects_stale_calibration(browser, tmp_path):
    wait = prepare(browser, tmp_path, connected=True)
    browser.execute_script("window.receiverState.preflight_state = 'ok'; window.receiverState.transfer_bpc = 2")
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: label(d) == "Start reception first")
    assert " f=0 " in browser.title


def test_silent_receiver_has_bounded_wait_and_sends_no_file(browser, tmp_path):
    wait = prepare(browser, tmp_path, connected=True)
    browser.execute_script("""
      window.fetch = (url, options) => new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('Aborted','AbortError')));
      });
    """)
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: label(d) == "Receiver unavailable")
    assert " f=0 " in browser.title


def test_cancelled_response_cannot_confirm_restarted_sender(browser, tmp_path):
    wait = prepare(browser, tmp_path, connected=True)
    browser.execute_script("""
      window.fetch = async () => {
        window.fetchCalls++;
        if (window.fetchCalls === 2) return new Promise(resolve => { window.oldResolve = resolve; });
        return {ok:true, json:async () => window.receiverState};
      };
    """)
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: d.execute_script("return !!window.oldResolve"))
    stop(browser)
    browser.execute_script("""
      const bpc = document.getElementById('bpcSelect');
      bpc.value='3'; bpc.dispatchEvent(new Event('change'));
    """)
    browser.find_element(By.ID, "startBtn").click()
    wait.until(lambda d: "[PREFLIGHT]" in d.title)
    browser.execute_script("window.oldResolve({ok:true, json:async () => ({active:true, preflight_required:true, preflight_state:'ok', transfer_bpc:1})})")
    # Wait for another fresh poll; the old response must not send or downgrade.
    calls = browser.execute_script("return window.fetchCalls")
    wait.until(lambda d: d.execute_script("return window.fetchCalls") > calls)
    assert "[PREFLIGHT]" in browser.title
    assert " f=0 " in browser.title
    assert browser.find_element(By.ID, "bpcSelect").get_attribute("value") == "3"
    stop(browser)
