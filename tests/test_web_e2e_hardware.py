from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pytest
import requests
from screeninfo import get_monitors
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


pytestmark = pytest.mark.hardware

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
CHROME_BINARY_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


@dataclass(frozen=True)
class MonitorGeometry:
    x: int
    y: int
    width: int
    height: int
    name: str


@dataclass(frozen=True)
class WebServerContext:
    base_url: str
    output_dir: Path
    log_path: Path
    device_index: int
    device_name: str
    sender_screen_index: int
    sender_monitor: MonitorGeometry
    receiver_monitor: MonitorGeometry


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _find_chrome_binary() -> str | None:
    for candidate in CHROME_BINARY_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None


def _wait_for_server_ready(base_url: str, log_path: Path, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last_error = "server did not answer"
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/api/receive/status", timeout=2.0)
            if response.ok:
                return
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(0.25)
    log_tail = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    raise RuntimeError(f"web server did not start: {last_error}\n{log_tail}")


def _select_sender_monitor() -> MonitorGeometry:
    monitors = list(get_monitors())
    if len(monitors) < 2:
        pytest.skip("real web E2E requires a second monitor for the sender output")

    requested = os.environ.get("HDMI_EXFIL_E2E_SENDER_MONITOR")
    selected = None
    if requested:
        try:
            index = int(requested) - 1
            if 0 <= index < len(monitors):
                selected = monitors[index]
        except ValueError:
            selected = None

    if selected is None:
        selected = next((m for m in monitors if not getattr(m, "is_primary", False)), monitors[1])

    return MonitorGeometry(
        x=int(selected.x),
        y=int(selected.y),
        width=int(selected.width),
        height=int(selected.height),
        name=str(selected.name),
    )


def _select_receiver_monitor() -> MonitorGeometry:
    primary = next((m for m in get_monitors() if getattr(m, "is_primary", False)), None)
    if primary is None:
        primary = list(get_monitors())[0]
    return MonitorGeometry(
        x=int(primary.x),
        y=int(primary.y),
        width=int(primary.width),
        height=int(primary.height),
        name=str(primary.name),
    )


def _resolve_screen_index(monitor: MonitorGeometry) -> int:
    monitors = list(get_monitors())
    for index, item in enumerate(monitors):
        if (
            int(item.x) == monitor.x
            and int(item.y) == monitor.y
            and int(item.width) == monitor.width
            and int(item.height) == monitor.height
        ):
            return index
    return 1 if len(monitors) > 1 else 0


def _select_capture_device(devices: list[dict[str, Any]]) -> dict[str, Any]:
    if not devices:
        pytest.skip("no capture devices detected for hardware web E2E")

    hint = os.environ.get("HDMI_EXFIL_E2E_CAPTURE_HINT", "elgato").strip().lower()
    if hint:
        for device in devices:
            if hint in str(device.get("name", "")).lower():
                return device

    for keyword in ("capture", "cam link", "hdmi"):
        for device in devices:
            if keyword in str(device.get("name", "")).lower():
                return device

    return max(
        devices,
        key=lambda device: (
            float(device.get("fps", 0.0)),
            int(device.get("width", 0)) * int(device.get("height", 0)),
        ),
    )


def _launch_server(output_dir: Path, log_path: Path) -> tuple[subprocess.Popen[str], str]:
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    runner = (
        "import sys\n"
        f"sys.path.insert(0, {str(SRC_ROOT)!r})\n"
        "from hdmi_exfil.web.server import create_app\n"
        f"app = create_app(output_dir={str(output_dir)!r})\n"
        f"app.run(host='127.0.0.1', port={port}, debug=False, threaded=True)\n"
    )
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", runner],
        cwd=str(REPO_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return process, base_url


@pytest.fixture(scope="module")
def web_server_context(tmp_path_factory: pytest.TempPathFactory) -> WebServerContext:
    output_dir = tmp_path_factory.mktemp("web-e2e-output")
    log_dir = tmp_path_factory.mktemp("web-e2e-log")
    log_path = log_dir / "server.log"
    process, base_url = _launch_server(output_dir, log_path)
    try:
        _wait_for_server_ready(base_url, log_path)
        response = requests.get(f"{base_url}/api/devices?force=1", timeout=60.0)
        response.raise_for_status()
        devices = response.json()
        device = _select_capture_device(devices)
        sender_monitor = _select_sender_monitor()
        requests.post(
            f"{base_url}/api/devices/warm",
            json={"device": int(device["index"])},
            timeout=10.0,
        )
        yield WebServerContext(
            base_url=base_url,
            output_dir=output_dir,
            log_path=log_path,
            device_index=int(device["index"]),
            device_name=str(device["name"]),
            sender_screen_index=_resolve_screen_index(sender_monitor),
            sender_monitor=sender_monitor,
            receiver_monitor=_select_receiver_monitor(),
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)


@contextlib.contextmanager
def _chrome_session(
    *,
    app_url: str | None = None,
    monitor: MonitorGeometry | None = None,
    width: int | None = None,
    height: int | None = None,
) -> webdriver.Chrome:
    profile_dir = Path(tempfile.mkdtemp(prefix="hdmi-exfil-web-e2e-"))
    options = Options()
    options.page_load_strategy = "eager"
    if app_url:
        options.add_argument(f"--app={app_url}")
    chrome_binary = _find_chrome_binary()
    if chrome_binary:
        options.binary_location = chrome_binary
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-features=Translate,CalculateNativeWinOcclusion")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--force-device-scale-factor=1")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if monitor is not None:
        options.add_argument(f"--window-position={monitor.x},{monitor.y}")
        options.add_argument(
            f"--window-size={width or monitor.width},{height or monitor.height}"
        )

    driver: webdriver.Chrome | None = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
    except WebDriverException as exc:
        pytest.skip(f"Chrome/Selenium unavailable for hardware web E2E: {exc}")
    try:
        assert driver is not None
        yield driver
    finally:
        if driver is not None:
            with contextlib.suppress(Exception):
                driver.quit()
        shutil.rmtree(profile_dir, ignore_errors=True)


def _wait_for_ready_state(
    driver: webdriver.Chrome,
    timeout_s: float = 30.0,
    sentinel_id: str = "startBtn",
) -> None:
    WebDriverWait(driver, timeout_s).until(
        lambda d: d.execute_script(
            """
            const sentinel = document.getElementById(arguments[0]);
            return document.readyState !== "loading" && !!sentinel;
            """,
            sentinel_id,
        )
    )


def _position_window(
    driver: webdriver.Chrome,
    monitor: MonitorGeometry,
    *,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    target_width = width or monitor.width
    target_height = height or monitor.height
    try:
        window = driver.execute_cdp_cmd("Browser.getWindowForTarget", {})
        driver.execute_cdp_cmd(
            "Browser.setWindowBounds",
            {
                "windowId": window["windowId"],
                "bounds": {
                    "left": monitor.x,
                    "top": monitor.y,
                    "width": target_width,
                    "height": target_height,
                    "windowState": "normal",
                },
            },
        )
    except Exception:
        driver.set_window_rect(
            x=monitor.x,
            y=monitor.y,
            width=target_width,
            height=target_height,
        )
    time.sleep(0.5)
    return driver.execute_script(
        "return {"
        "screenX: window.screenX, screenY: window.screenY, "
        "outerWidth: window.outerWidth, outerHeight: window.outerHeight, "
        "innerWidth: window.innerWidth, innerHeight: window.innerHeight"
        "};"
    )


def _set_select_value(driver: webdriver.Chrome, element_id: str, value: str) -> None:
    driver.execute_script(
        """
        const el = document.getElementById(arguments[0]);
        el.value = String(arguments[1]);
        el.dispatchEvent(new Event("change", {bubbles: true}));
        """,
        element_id,
        value,
    )


def _set_checkbox_value(driver: webdriver.Chrome, element_id: str, checked: bool) -> None:
    driver.execute_script(
        """
        const el = document.getElementById(arguments[0]);
        el.checked = !!arguments[1];
        el.dispatchEvent(new Event("change", {bubbles: true}));
        """,
        element_id,
        checked,
    )


def _set_input_value(driver: webdriver.Chrome, element_id: str, value: str) -> None:
    driver.execute_script(
        """
        const el = document.getElementById(arguments[0]);
        el.value = String(arguments[1]);
        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
        """,
        element_id,
        value,
    )


def _wait_for_receiver_devices(driver: webdriver.Chrome, timeout_s: float = 60.0) -> None:
    WebDriverWait(driver, timeout_s).until(
        lambda d: d.execute_script(
            """
            const el = document.getElementById("deviceSelect");
            if (!el || el.disabled || !el.options.length) return false;
            return !["Scanning...", "No devices", "Error"].includes(el.options[0].textContent.trim());
            """
        )
    )


def _wait_for_receiver_stream_ready(driver: webdriver.Chrome, timeout_s: float = 30.0) -> None:
    WebDriverWait(driver, timeout_s).until(
        lambda d: d.execute_script(
            """
            const status = document.getElementById("statusMsg").textContent || "";
            const logs = document.getElementById("logBody").textContent || "";
            return logs.includes("Device opened:") && (status.includes("Waiting for") || logs.includes("Waiting for"));
            """
        )
    )


def _upload_file(driver: webdriver.Chrome, payload_path: Path) -> None:
    file_input = driver.find_element(By.ID, "fileInput")
    file_input.send_keys(str(payload_path))
    WebDriverWait(driver, 30.0).until(
        lambda d: d.find_element(By.ID, "fileName").text == payload_path.name
    )
    WebDriverWait(driver, 30.0).until(
        lambda d: not d.find_element(By.ID, "startBtn").get_property("disabled")
    )


def _receiver_debug_state(driver: webdriver.Chrome) -> dict[str, Any]:
    return driver.execute_script(
        """
        function textOr(selector, fallback = "") {
          const node = document.querySelector(selector);
          return node ? node.textContent.trim() : fallback;
        }
        const logLines = Array.from(document.querySelectorAll("#logBody .log-msg"))
          .slice(-8)
          .map((node) => node.textContent.trim());
        return {
          status: textOr("#statusMsg"),
          pct: textOr("#pctBig"),
          name: textOr("#metricName", "--"),
          sha: textOr("#metricSha", "--"),
          speed: textOr("#metricSpeed", "--"),
          counts: Array.from(document.querySelectorAll(".fountain-counts span")).map((node) => node.textContent.trim()),
          logs: logLines,
        };
        """
    )


def _bring_to_front(driver: webdriver.Chrome) -> None:
    with contextlib.suppress(Exception):
        driver.execute_cdp_cmd("Page.bringToFront", {})
    with contextlib.suppress(Exception):
        driver.execute_script("window.focus();")
    time.sleep(0.2)


def _fullscreen_window(driver: webdriver.Chrome, monitor: MonitorGeometry) -> None:
    window = driver.execute_cdp_cmd("Browser.getWindowForTarget", {})
    driver.execute_cdp_cmd(
        "Browser.setWindowBounds",
        {
            "windowId": window["windowId"],
            "bounds": {
                "left": monitor.x,
                "top": monitor.y,
                "width": monitor.width,
                "height": monitor.height,
                "windowState": "normal",
            },
        },
    )
    time.sleep(0.2)
    driver.execute_cdp_cmd(
        "Browser.setWindowBounds",
        {"windowId": window["windowId"], "bounds": {"windowState": "fullscreen"}},
    )
    time.sleep(0.4)


def _sender_debug_state(driver: webdriver.Chrome) -> dict[str, Any]:
    return driver.execute_script(
        """
        return {
          status: document.getElementById("statusLabel").textContent.trim(),
          frames: document.getElementById("headerFrames").textContent.trim(),
          chunks: document.getElementById("headerK").textContent.trim(),
          warning: document.getElementById("configWarning").textContent.trim(),
          geom: {
            screenX: window.screenX,
            screenY: window.screenY,
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight,
            fullscreen: !!document.fullscreenElement,
            visibility: document.visibilityState,
          },
        };
        """
    )


def _sender_frame_count(driver: webdriver.Chrome) -> int:
    value = driver.find_element(By.ID, "headerFrames").text.strip()
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return 0


def _receiver_status_snapshot(base_url: str) -> dict[str, Any]:
    response = requests.get(f"{base_url}/api/receive/status", timeout=5.0)
    response.raise_for_status()
    return response.json()


def _receiver_status_signature(status: dict[str, Any]) -> tuple[Any, ...]:
    return (
        status.get("active"),
        status.get("state"),
        status.get("message"),
        status.get("protocol"),
        status.get("preflight_state"),
        status.get("low_signal_streak"),
        status.get("low_signal_detected"),
        status.get("percent"),
        status.get("chunks_decoded"),
        status.get("total_chunks"),
        status.get("bytes_received"),
        status.get("download_url"),
        status.get("last_event_type"),
    )


def _receiver_metrics_from_status(status: dict[str, Any]) -> dict[str, str] | None:
    if status.get("state") != "complete":
        return None
    download_url = status.get("download_url")
    if not download_url:
        return None

    sha_available = bool(status.get("sha256_available"))
    sha_ok = bool(status.get("sha256_ok"))
    if sha_ok:
        sha = "OK"
    elif sha_available:
        sha = "FAIL"
    else:
        sha = "UNAVAILABLE"

    duration_s = float(status.get("duration_s", 0.0) or 0.0)
    speed_mbps = float(status.get("speed_mbps", 0.0) or 0.0)
    return {
        "name": str(status.get("filename", "")).strip(),
        "size": str(status.get("size", "")).strip(),
        "sha": sha,
        "duration": f"{duration_s:.2f} s",
        "speed": f"{speed_mbps:.2f} Mbps",
        "download": str(download_url).strip(),
    }


def _receiver_wait_failure_reason(status: dict[str, Any], *, stagnant_s: float) -> str:
    state = str(status.get("state", "")).strip() or "unknown"
    if state == "preflight_wait":
        preview_age_s = status.get("preview_age_s")
        try:
            preview_age_s = float(preview_age_s)
        except (TypeError, ValueError):
            preview_age_s = None
        if preview_age_s is not None and preview_age_s >= 3.0:
            return "receiver remained blocked in HDMI preflight and preview stream stalled"
        if bool(status.get("low_signal_detected")):
            return "receiver remained blocked in HDMI preflight with black or low-signal preview"
        return "receiver remained blocked in HDMI preflight"
    if state == "error":
        return f"receiver entered error state: {status.get('message', 'Error')}"
    if state == "stopped":
        return f"receiver stopped before completion: {status.get('message', 'Stopped')}"
    if not bool(status.get("active", True)) and state != "complete":
        return f"receiver became inactive without completion (state={state})"
    if stagnant_s > 0:
        return f"receiver stalled before completion (state={state})"
    return f"receiver never reached completion (state={state})"


def _resolve_sender_debug_snapshot(sender_debug: Any) -> Any:
    if not callable(sender_debug):
        return sender_debug
    try:
        return sender_debug()
    except Exception as exc:
        return {"sender_debug_error": str(exc)}


def _wait_for_receiver_completion(
    driver: webdriver.Chrome,
    *,
    base_url: str,
    timeout_s: float,
    sender_debug: Any,
    stall_timeout_s: float = 15.0,
    preflight_timeout_s: float = 8.0,
    poll_interval_s: float = 0.25,
) -> dict[str, str]:
    deadline = time.time() + timeout_s
    last_signature: tuple[Any, ...] | None = None
    last_change_at = time.time()
    last_status: dict[str, Any] = {"state": "unknown", "active": True}
    last_sender_state: Any = {}
    preflight_wait_started_at: float | None = None

    while time.time() < deadline:
        try:
            status = _receiver_status_snapshot(base_url)
        except Exception as exc:
            status = {
                "state": "status_unavailable",
                "message": str(exc),
                "active": True,
            }

        last_status = status
        last_sender_state = _resolve_sender_debug_snapshot(sender_debug)
        sender_status = str(
            last_sender_state.get("status", "")
            if isinstance(last_sender_state, dict)
            else "",
        ).strip()
        signature = _receiver_status_signature(status)
        if signature != last_signature:
            last_signature = signature
            last_change_at = time.time()

        metrics = _receiver_metrics_from_status(status)
        if metrics is not None:
            return metrics

        state = str(status.get("state", "")).strip()
        if state == "preflight_wait":
            preview_age_s = status.get("preview_age_s")
            try:
                preview_age_value = float(preview_age_s)
            except (TypeError, ValueError):
                preview_age_value = None
            if preview_age_value is not None and preview_age_value >= 3.0:
                break
            if preflight_wait_started_at is None:
                preflight_wait_started_at = time.time()
            sender_is_still_negotiating = sender_status in {"Starting", "Preflight"}
            effective_preflight_timeout_s = (
                max(preflight_timeout_s, 20.0)
                if sender_is_still_negotiating
                else preflight_timeout_s
            )
            if sender_status in {"Preflight failed", "Receiver timeout", "Stopped"}:
                break
            elif (
                time.time() - preflight_wait_started_at >= effective_preflight_timeout_s
                and (
                    not sender_is_still_negotiating
                    or time.time() - last_change_at >= 2.0
                )
            ):
                break
        else:
            preflight_wait_started_at = None

        if sender_status in {"Preflight failed", "Receiver timeout", "Stopped"}:
            break
        if state in {"error", "stopped"}:
            break
        if not bool(status.get("active", True)) and state != "complete":
            break
        if time.time() - last_change_at >= stall_timeout_s:
            break
        time.sleep(poll_interval_s)

    receiver_state = _receiver_debug_state(driver)
    sender_state = last_sender_state
    reason = _receiver_wait_failure_reason(
        last_status,
        stagnant_s=max(0.0, time.time() - last_change_at),
    )
    raise AssertionError(
        "receiver did not complete\n"
        f"reason={reason}\n"
        f"receiver_api={last_status}\n"
        f"receiver_ui={receiver_state}\n"
        f"sender={sender_state}"
    )


def _download_received_bytes(base_url: str, download_url: str, timeout_s: float = 20.0) -> bytes:
    absolute_url = urljoin(base_url, download_url)
    deadline = time.time() + timeout_s
    last_error = "download unavailable"
    while time.time() < deadline:
        try:
            response = requests.get(absolute_url, timeout=10.0)
            if response.ok:
                return response.content
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise AssertionError(f"receiver download never became available: {last_error}")


def _reset_receiver(base_url: str, device_index: int) -> None:
    requests.post(
        f"{base_url}/api/receive/reset",
        json={"device": device_index},
        timeout=15.0,
    )


def _create_payload(tmp_path: Path, mode: str, size_bytes: int = 1024 * 1024) -> tuple[Path, bytes]:
    payload = bytes(((index * 73) + 19) % 256 for index in range(size_bytes))
    payload_path = tmp_path / f"web-ui-{mode}-e2e.bin"
    payload_path.write_bytes(payload)
    return payload_path, payload


def _launch_python_sender(
    payload_path: Path,
    *,
    mode: str,
    screen_index: int,
    log_path: Path,
    bits_per_channel: int = 3,
    fountain_redundancy: float = 2.0,
    sequential_data_repeat: int = 3,
    sequential_metadata_repeat: int = 12,
    sequential_passes: int = 2,
) -> subprocess.Popen[str]:
    runner = (
        "import math\n"
        "import sys\n"
        "import time\n"
        "from dataclasses import replace\n"
        "import numpy as np\n"
        f"sys.path.insert(0, {str(SRC_ROOT)!r})\n"
        "from hdmi_exfil.core.config import PROFILES\n"
        "from hdmi_exfil.core.file_handling.metadata import build_start_metadata\n"
        "from hdmi_exfil.core.file_handling.reader import read_input\n"
        "from hdmi_exfil.core.prng import choose_indices\n"
        "from hdmi_exfil.core.protocols import get_protocol\n"
        "from hdmi_exfil.core.protocols.xor_ops import warmup as warmup_numba, xor_into\n"
        "from hdmi_exfil.sender.display.monitors import get_monitors\n"
        "from hdmi_exfil.sender.display.renderer import PygameRenderer\n"
        "\n"
        "def main() -> None:\n"
        "    input_path = sys.argv[1]\n"
        "    mode = sys.argv[2]\n"
        "    screen = int(sys.argv[3])\n"
        "    bits_per_channel = int(sys.argv[4])\n"
        "    fountain_redundancy = float(sys.argv[5])\n"
        "    sequential_data_repeat = int(sys.argv[6])\n"
        "    sequential_metadata_repeat = int(sys.argv[7])\n"
        "    sequential_passes = int(sys.argv[8])\n"
        "    profile = replace(PROFILES['balanced'], bits_per_channel=bits_per_channel)\n"
        "    filename, file_data = read_input(input_path)\n"
        "    monitors = get_monitors()\n"
        "    target = monitors[screen]\n"
        "    print(f'sender_screen={screen} pos=({target[\"left\"]},{target[\"top\"]}) size={target[\"width\"]}x{target[\"height\"]}', flush=True)\n"
        "    protocol = get_protocol(mode, profile=profile)\n"
        "    with PygameRenderer(width=profile.width, height=profile.height, x_offset=target['left'], y_offset=target['top']) as renderer:\n"
        "        if mode == 'fountain':\n"
        "            warmup_numba()\n"
        "            metadata = build_start_metadata(filename, file_data)\n"
        "            wrapped = metadata + file_data\n"
        "            payload_size = profile.fount_bytes_per_frame\n"
        "            K = math.ceil(len(wrapped) / payload_size)\n"
        "            chunks = []\n"
        "            for i in range(K):\n"
        "                start = i * payload_size\n"
        "                end = min(start + payload_size, len(wrapped))\n"
        "                chunk = np.zeros(payload_size, dtype=np.uint8)\n"
        "                chunk[:end - start] = np.frombuffer(wrapped[start:end], dtype=np.uint8)\n"
        "                chunks.append(chunk)\n"
        "            max_droplets = int(math.ceil(K * fountain_redundancy))\n"
        "            seed = 1\n"
        "            for frame_count in range(max_droplets):\n"
        "                payload = np.zeros(payload_size, dtype=np.uint8)\n"
        "                for idx in choose_indices(seed, K):\n"
        "                    xor_into(payload, chunks[idx])\n"
        "                frame = protocol.encode_frame(payload.tobytes(), frame_count, K, seed=seed, expected_droplets=max_droplets)\n"
        "                renderer.show(frame, delay_ms=1)\n"
        "                seed = (seed + 1) & 0xFFFFFFFF\n"
        "                if seed == 0:\n"
        "                    seed = 1\n"
        "        else:\n"
        "            bytes_per_frame = profile.seq_bytes_per_frame\n"
        "            total_frames = math.ceil(len(file_data) / bytes_per_frame)\n"
        "            start_frame = protocol.encode_start_frame(filename, file_data, total_frames)\n"
        "            end_frame = protocol.encode_end_frame(total_frames)\n"
        "            for _pass in range(sequential_passes):\n"
        "                for _ in range(sequential_metadata_repeat):\n"
        "                    renderer.show(start_frame, delay_ms=1)\n"
        "                for i in range(total_frames):\n"
        "                    start = i * bytes_per_frame\n"
        "                    end = min((i + 1) * bytes_per_frame, len(file_data))\n"
        "                    frame = protocol.encode_frame(file_data[start:end], i, total_frames)\n"
        "                    for _ in range(sequential_data_repeat):\n"
        "                        renderer.show(frame, delay_ms=1)\n"
        "                for _ in range(sequential_metadata_repeat):\n"
        "                    renderer.show(end_frame, delay_ms=1)\n"
        "        blank = np.zeros((profile.height, profile.width, 3), dtype=np.uint8)\n"
        "        for _ in range(20):\n"
        "            renderer.show(blank, delay_ms=1)\n"
        "        time.sleep(0.5)\n"
        "    print('sender_done', flush=True)\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    log_file = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            runner,
            str(payload_path),
            mode,
            str(screen_index),
            str(bits_per_channel),
            str(fountain_redundancy),
            str(sequential_data_repeat),
            str(sequential_metadata_repeat),
            str(sequential_passes),
        ],
        cwd=str(REPO_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_sender_process(process: subprocess.Popen[str], log_path: Path, timeout_s: float = 120.0) -> None:
    try:
        return_code = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait(timeout=5.0)
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        raise AssertionError(f"python sender timed out\n{log_text}") from exc

    if return_code != 0:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        raise AssertionError(f"python sender failed with exit code {return_code}\n{log_text}")


@pytest.mark.parametrize("mode", ["fountain", "sequential"])
def test_web_ui_real_hardware_transfer(
    tmp_path: Path,
    web_server_context: WebServerContext,
    mode: str,
) -> None:
    payload_path, payload = _create_payload(tmp_path, mode)
    payload_sha = hashlib.sha256(payload).hexdigest()

    receiver_url = web_server_context.base_url
    sender_log_path = tmp_path / f"python-sender-{mode}.log"

    try:
        with _chrome_session(
            monitor=web_server_context.receiver_monitor,
            width=max(1200, min(1600, web_server_context.receiver_monitor.width)),
            height=max(900, min(1040, web_server_context.receiver_monitor.height)),
        ) as receiver_driver:
            receiver_driver.get(receiver_url)
            _wait_for_ready_state(receiver_driver)
            _position_window(
                receiver_driver,
                web_server_context.receiver_monitor,
                width=max(1200, min(1600, web_server_context.receiver_monitor.width)),
                height=max(900, min(1040, web_server_context.receiver_monitor.height)),
            )

            _wait_for_receiver_devices(receiver_driver)
            _set_select_value(receiver_driver, "deviceSelect", str(web_server_context.device_index))
            _set_select_value(receiver_driver, "profileSelect", "balanced")
            _set_select_value(receiver_driver, "modeSelect", mode)
            _set_select_value(receiver_driver, "bpcSelect", "3")
            _set_select_value(receiver_driver, "previewQualitySelect", "45")

            receiver_driver.find_element(By.ID, "startBtn").click()
            WebDriverWait(receiver_driver, 20.0).until(
                lambda d: not d.find_element(By.ID, "stopBtn").get_property("disabled")
            )
            _wait_for_receiver_stream_ready(receiver_driver)

            sender_process = _launch_python_sender(
                payload_path,
                mode=mode,
                screen_index=web_server_context.sender_screen_index,
                log_path=sender_log_path,
            )
            _wait_for_sender_process(sender_process, sender_log_path, timeout_s=120.0)

            time.sleep(2.0)
            metrics = _wait_for_receiver_completion(
                receiver_driver,
                base_url=receiver_url,
                timeout_s=90.0,
                sender_debug={
                    "sender_log": sender_log_path.read_text(encoding="utf-8", errors="replace")
                },
            )

            if mode == "fountain":
                assert metrics["name"] == payload_path.name
                assert metrics["sha"] == "OK"
            else:
                assert metrics["name"] == payload_path.name or metrics["name"].startswith("received_")
                assert metrics["sha"] in {"OK", "UNAVAILABLE"}
            assert metrics["download"]
            assert metrics["speed"].endswith("Mbps")

            downloaded = _download_received_bytes(
                web_server_context.base_url,
                metrics["download"],
            )
            assert downloaded == payload, (
                f"downloaded payload mismatch for {mode}: "
                f"expected_sha={payload_sha}"
            )
    finally:
        with contextlib.suppress(Exception):
            _reset_receiver(web_server_context.base_url, web_server_context.device_index)
