from __future__ import annotations

import argparse
import ctypes
import contextlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

import requests
from selenium.webdriver.common.by import By

from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_web_e2e_hardware import (  # noqa: E402
    _bring_to_front,
    _chrome_session,
    _create_payload,
    _download_received_bytes,
    _find_chrome_binary,
    _fullscreen_window,
    _position_window,
    _receiver_debug_state,
    _reset_receiver,
    _select_capture_device,
    _select_receiver_monitor,
    _select_sender_monitor,
    _sender_debug_state,
    _set_select_value,
    _wait_for_ready_state,
    _wait_for_receiver_completion,
    _wait_for_receiver_devices,
    _wait_for_receiver_stream_ready,
    _launch_server,
    _wait_for_server_ready,
)


@dataclass
class BenchmarkCase:
    label: str
    mode: str
    bits_per_channel: int
    fountain_redundancy: float = 2.0
    sequential_repeat: int = 1


@dataclass
class BenchmarkResult:
    label: str
    mode: str
    bits_per_channel: int
    file_size_bytes: int
    duration_s: float
    measured_speed_mbps: float
    ui_duration_s: float
    ui_speed_mbps: float
    sender_frames: int
    ui_name: str
    ui_sha: str
    ok: bool
    error: str = ""


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _parse_metric_float(value: str) -> float:
    token = value.strip().replace(",", ".").split()[0]
    return float(token.rstrip("s"))


def _build_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase("fountain_bpc2_r1.50", "fountain", 2, fountain_redundancy=1.50),
        BenchmarkCase("fountain_bpc3_r1.25", "fountain", 3, fountain_redundancy=1.25),
        BenchmarkCase("fountain_bpc3_r1.50", "fountain", 3, fountain_redundancy=1.50),
        BenchmarkCase("fountain_bpc3_r2.00", "fountain", 3, fountain_redundancy=2.00),
        BenchmarkCase("sequential_bpc2_rep1", "sequential", 2, sequential_repeat=1),
        BenchmarkCase("sequential_bpc2_rep2", "sequential", 2, sequential_repeat=2),
        BenchmarkCase("sequential_bpc3_rep1", "sequential", 3, sequential_repeat=1),
        BenchmarkCase("sequential_bpc3_rep2", "sequential", 3, sequential_repeat=2),
        BenchmarkCase("sequential_bpc3_rep3", "sequential", 3, sequential_repeat=3),
        BenchmarkCase("sequential_bpc3_rep4", "sequential", 3, sequential_repeat=4),
    ]


def _select_cases(all_cases: Iterable[BenchmarkCase], labels: list[str] | None) -> list[BenchmarkCase]:
    cases = list(all_cases)
    if not labels:
        return cases

    wanted = {label.strip() for label in labels if label.strip()}
    selected = [case for case in cases if case.label in wanted]
    missing = sorted(wanted - {case.label for case in selected})
    if missing:
        raise SystemExit(f"unknown benchmark labels: {', '.join(missing)}")
    return selected


def _write_results(
    output_path: Path,
    *,
    size_mib: int,
    sender_monitor: object,
    device: dict[str, object],
    results: list[BenchmarkResult],
) -> None:
    payload_json = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "size_mib": size_mib,
        "sender_monitor": asdict(sender_monitor),
        "device": device,
        "results": [asdict(item) for item in results],
    }
    output_path.write_text(json.dumps(payload_json, indent=2), encoding="utf-8")


def _launch_static_server(directory: Path, log_path: Path) -> tuple[subprocess.Popen[str], str]:
    port = _find_free_port()
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(directory),
        ],
        cwd=str(ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/sender.html", timeout=2.0)
            if response.ok:
                return process, base_url
        except requests.RequestException:
            pass
        time.sleep(0.25)
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)
    raise RuntimeError(f"static sender server did not start: {log_path.read_text(encoding='utf-8', errors='replace')}")


def _terminate_process(process: subprocess.Popen[str], timeout_s: float = 10.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


def _promote_window(process_id: int, sender_monitor) -> None:
    user32 = ctypes.windll.user32
    hwnd_found = None

    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    IsWindowVisible = user32.IsWindowVisible
    AdjustWindowRectEx = user32.AdjustWindowRectEx
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowLongPtr = user32.GetWindowLongPtrW
    ShowWindow = user32.ShowWindow
    SetForegroundWindow = user32.SetForegroundWindow
    MoveWindow = user32.MoveWindow
    SetWindowPos = user32.SetWindowPos

    SW_RESTORE = 9
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040

    GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    GetWindowLongPtr.restype = ctypes.c_ssize_t
    AdjustWindowRectEx.argtypes = [
        ctypes.POINTER(wintypes.RECT),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    AdjustWindowRectEx.restype = wintypes.BOOL

    def callback(hwnd, _lparam):
        nonlocal hwnd_found
        if not IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process_id:
            hwnd_found = hwnd
            return False
        return True

    deadline = time.time() + 10.0
    while time.time() < deadline and hwnd_found is None:
        EnumWindows(EnumWindowsProc(callback), 0)
        if hwnd_found is None:
            time.sleep(0.2)
    if hwnd_found is None:
        return

    ShowWindow(hwnd_found, SW_RESTORE)
    style = GetWindowLongPtr(hwnd_found, GWL_STYLE)
    ex_style = GetWindowLongPtr(hwnd_found, GWL_EXSTYLE)
    rect = wintypes.RECT(0, 0, int(sender_monitor.width), int(sender_monitor.height))
    if AdjustWindowRectEx(ctypes.byref(rect), style, False, ex_style):
        left = int(sender_monitor.x) + int(rect.left)
        top = int(sender_monitor.y) + int(rect.top)
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
    else:
        left = int(sender_monitor.x)
        top = int(sender_monitor.y)
        width = int(sender_monitor.width)
        height = int(sender_monitor.height)
    MoveWindow(
        hwnd_found,
        left,
        top,
        width,
        height,
        True,
    )
    SetWindowPos(
        hwnd_found,
        HWND_TOPMOST,
        left,
        top,
        width,
        height,
        SWP_SHOWWINDOW,
    )
    SetForegroundWindow(hwnd_found)
    time.sleep(0.5)
    SetWindowPos(hwnd_found, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)


def _build_sender_url(
    sender_base_url: str,
    payload_name: str,
    case: BenchmarkCase,
    *,
    api_base_url: str = "",
) -> str:
    params: dict[str, str] = {
        "protocol": case.mode,
        "bpc": str(case.bits_per_channel),
        "profile": "balanced",
        "fpsMode": "profile",
        "payload": f"/{payload_name}",
        "name": payload_name,
        "autostart": "1",
    }
    if api_base_url:
        params["apiBaseUrl"] = api_base_url
    if case.mode == "fountain":
        params["fountainAutoStop"] = "1"
        params["fountainRedundancy"] = f"{case.fountain_redundancy:.2f}"
    else:
        params["sequentialRepeat"] = str(case.sequential_repeat)
    return f"{sender_base_url}/sender.html?{urlencode(params)}"


def _launch_sender_app(sender_url: str, sender_monitor) -> tuple[subprocess.Popen[str], Path]:
    chrome_binary = _find_chrome_binary()
    if not chrome_binary:
        raise RuntimeError("Chrome binary not found")
    profile_dir = Path(tempfile.mkdtemp(prefix="hdmi-bench-sender-profile-"))
    default_dir = profile_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    (default_dir / "Preferences").write_text(
        json.dumps(
            {
                "translate": {"enabled": False},
                "intl": {"accept_languages": "en-US,en"},
                "browser": {"check_default_browser": False},
            }
        ),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            chrome_binary,
            f"--app={sender_url}",
            "--lang=en-US",
            "--disable-translate",
            "--disable-extensions",
            "--disable-component-extensions-with-background-pages",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=Translate,CalculateNativeWinOcclusion",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-notifications",
            "--force-device-scale-factor=1",
            f"--user-data-dir={profile_dir}",
            f"--window-position={sender_monitor.x},{sender_monitor.y}",
            f"--window-size={sender_monitor.width},{sender_monitor.height}",
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    time.sleep(4.0)
    _promote_window(process.pid, sender_monitor)
    return process, profile_dir


def _wait_for_output_file(
    output_dir: Path,
    *,
    known_files: set[str],
    timeout_s: float,
) -> Path:
    deadline = time.time() + timeout_s
    candidate: Path | None = None
    last_size = -1
    stable_since = 0.0
    while time.time() < deadline:
        files = sorted(
            path for path in output_dir.iterdir() if path.is_file() and path.name not in known_files
        )
        if files:
            candidate = files[-1]
            size = candidate.stat().st_size
            if size > 0 and size == last_size:
                if stable_since == 0.0:
                    stable_since = time.time()
                elif time.time() - stable_since >= 1.0:
                    return candidate
            else:
                last_size = size
                stable_since = 0.0
        time.sleep(0.25)
    raise AssertionError(
        f"no completed output file appeared in {output_dir} within {timeout_s:.1f}s"
    )


def _wait_for_case_result(
    *,
    receiver_driver,
    base_url: str,
    output_dir: Path,
    known_files: set[str],
    sender_url: str,
    sender_debug: dict[str, object],
    completion_timeout_s: float,
    output_timeout_s: float,
) -> tuple[dict[str, str], Path | None, float]:
    started = time.perf_counter()
    metrics = _wait_for_receiver_completion(
        receiver_driver,
        base_url=base_url,
        timeout_s=completion_timeout_s,
        sender_debug=sender_debug,
    )
    duration_s = time.perf_counter() - started
    _bring_to_front(receiver_driver)
    output_file: Path | None = None
    try:
        output_file = _wait_for_output_file(
            output_dir,
            known_files=known_files,
            timeout_s=output_timeout_s,
        )
    except Exception:
        output_file = None
    return metrics, output_file, duration_s


def _run_case(
    *,
    base_url: str,
    output_dir: Path,
    sender_base_url: str,
    device_index: int,
    sender_monitor,
    case: BenchmarkCase,
    payload_path: Path,
    payload: bytes,
) -> BenchmarkResult:
    receiver_monitor = _select_receiver_monitor()
    sender_url = _build_sender_url(
        sender_base_url,
        payload_path.name,
        case,
        api_base_url=base_url,
    )

    try:
        with _chrome_session(
            monitor=receiver_monitor,
            width=max(1200, min(1600, receiver_monitor.width)),
            height=max(900, min(1040, receiver_monitor.height)),
        ) as receiver_driver:
            receiver_driver.get(base_url)
            _wait_for_ready_state(receiver_driver)
            _position_window(
                receiver_driver,
                receiver_monitor,
                width=max(1200, min(1600, receiver_monitor.width)),
                height=max(900, min(1040, receiver_monitor.height)),
            )
            _wait_for_receiver_devices(receiver_driver)
            _set_select_value(receiver_driver, "deviceSelect", str(device_index))
            _set_select_value(receiver_driver, "profileSelect", "balanced")
            _set_select_value(receiver_driver, "modeSelect", case.mode)
            _set_select_value(receiver_driver, "bpcSelect", str(case.bits_per_channel))
            _set_select_value(receiver_driver, "previewQualitySelect", "45")
            receiver_driver.find_element(By.ID, "startBtn").click()
            _wait_for_receiver_stream_ready(receiver_driver)

            known_files = {path.name for path in output_dir.iterdir() if path.is_file()}
            try:
                with _chrome_session(
                    app_url=sender_url,
                    monitor=sender_monitor,
                    width=sender_monitor.width,
                    height=sender_monitor.height,
                ) as sender_driver:
                    _wait_for_ready_state(sender_driver)
                    _position_window(
                        sender_driver,
                        sender_monitor,
                        width=sender_monitor.width,
                        height=sender_monitor.height,
                    )
                    _bring_to_front(sender_driver)
                    _fullscreen_window(sender_driver, sender_monitor)
                    metrics, output_file, duration_s = _wait_for_case_result(
                        receiver_driver=receiver_driver,
                        base_url=base_url,
                        output_dir=output_dir,
                        known_files=known_files,
                        sender_url=sender_url,
                        sender_debug=lambda: _sender_debug_state(sender_driver),
                        completion_timeout_s=300.0,
                        output_timeout_s=30.0,
                    )
            except Exception as exc:
                receiver_state = _receiver_debug_state(receiver_driver)
                raise AssertionError(
                    f"{exc}\nreceiver={receiver_state}\nsender_url={sender_url}"
                ) from exc
            received = _download_received_bytes(base_url, metrics["download"])
            if received != payload:
                raise AssertionError(f"{case.label}: downloaded payload mismatch")
            if output_file is not None and output_file.name != metrics["name"]:
                raise AssertionError(
                    f"{case.label}: receiver UI name mismatch "
                    f"(ui={metrics['name']} output={output_file.name})"
                )
            ui_speed_mbps = _parse_metric_float(metrics["speed"])
            ui_duration_s = _parse_metric_float(metrics["duration"])
            measured_speed_mbps = (len(payload) * 8.0) / duration_s / 1_000_000.0

            return BenchmarkResult(
                label=case.label,
                mode=case.mode,
                bits_per_channel=case.bits_per_channel,
                file_size_bytes=len(payload),
                duration_s=duration_s,
                measured_speed_mbps=measured_speed_mbps,
                ui_duration_s=ui_duration_s,
                ui_speed_mbps=ui_speed_mbps,
                sender_frames=0,
                ui_name=metrics["name"],
                ui_sha=metrics["sha"],
                ok=True,
                error="",
            )
    finally:
        with contextlib.suppress(Exception):
            _reset_receiver(base_url, device_index)


def main() -> None:
    parser = argparse.ArgumentParser(description="Real hardware UI benchmark sweep")
    parser.add_argument("--size-mib", type=int, default=50)
    parser.add_argument("--output", type=Path, default=ROOT / "hardware_ui_benchmark_results.json")
    parser.add_argument(
        "--labels",
        nargs="*",
        help="optional benchmark labels to run, e.g. fountain_bpc3_r1.50 sequential_bpc3_rep2",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list available benchmark labels and exit",
    )
    args = parser.parse_args()

    sender_monitor = _select_sender_monitor()
    all_cases = _build_cases()
    if args.list:
        for case in all_cases:
            print(case.label)
        return
    cases = _select_cases(all_cases, args.labels)

    with TemporaryDirectory(prefix="hdmi-hw-bench-") as tmpdir:
        tmp = Path(tmpdir)
        server_output = tmp / "received"
        server_output.mkdir()
        sender_bundle = tmp / "sender_bundle"
        sender_bundle.mkdir()
        server_log = tmp / "server.log"
        sender_static_log = tmp / "sender-static.log"
        shutil.copy2(ROOT / "sender.html", sender_bundle / "sender.html")
        payload_path, payload = _create_payload(
            sender_bundle,
            f"benchmark_{args.size_mib}mb",
            size_bytes=args.size_mib * 1024 * 1024,
        )
        sender_process, sender_base_url = _launch_static_server(sender_bundle, sender_static_log)
        try:
            results: list[BenchmarkResult] = []
            device: dict[str, object] = {}
            for case in cases:
                print(f"[bench] {case.label}", flush=True)
                started = time.perf_counter()
                process, base_url = _launch_server(server_output, server_log)
                try:
                    _wait_for_server_ready(base_url, server_log)
                    response = requests.get(f"{base_url}/api/devices?force=1", timeout=60.0)
                    response.raise_for_status()
                    device = _select_capture_device(response.json())
                    requests.post(
                        f"{base_url}/api/devices/warm",
                        json={"device": int(device["index"])},
                        timeout=10.0,
                    )
                    result = _run_case(
                        base_url=base_url,
                        output_dir=server_output,
                        sender_base_url=sender_base_url,
                        device_index=int(device["index"]),
                        sender_monitor=sender_monitor,
                        case=case,
                        payload_path=payload_path,
                        payload=payload,
                    )
                except Exception as exc:
                    result = BenchmarkResult(
                        label=case.label,
                        mode=case.mode,
                        bits_per_channel=case.bits_per_channel,
                        file_size_bytes=len(payload),
                        duration_s=time.perf_counter() - started,
                        measured_speed_mbps=0.0,
                        ui_duration_s=0.0,
                        ui_speed_mbps=0.0,
                        sender_frames=0,
                        ui_name="",
                        ui_sha="",
                        ok=False,
                        error=str(exc),
                    )
                finally:
                    _terminate_process(process, timeout_s=10.0)
                results.append(result)
                _write_results(
                    args.output,
                    size_mib=args.size_mib,
                    sender_monitor=sender_monitor,
                    device=device,
                    results=results,
                )
                if result.ok:
                    print(
                        f"[bench] done {case.label}: measured={result.measured_speed_mbps:.2f} Mbps, "
                        f"ui={result.ui_speed_mbps:.2f} Mbps, {result.duration_s:.2f}s, "
                        f"sha={result.ui_sha}, name={result.ui_name}",
                        flush=True,
                    )
                else:
                    print(
                        f"[bench] failed {case.label}: {result.duration_s:.2f}s | {result.error}",
                        flush=True,
                    )

            payload_json = json.loads(args.output.read_text(encoding="utf-8"))
            print(json.dumps(payload_json, indent=2))
        finally:
            _terminate_process(sender_process, timeout_s=5.0)


if __name__ == "__main__":
    main()
