from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

import requests
from selenium.webdriver.common.by import By

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_web_e2e_hardware import (  # noqa: E402
    _bring_to_front,
    _chrome_session,
    _download_received_bytes,
    _fullscreen_window,
    _position_window,
    _receiver_debug_state,
    _reset_receiver,
    _select_capture_device,
    _select_receiver_monitor,
    _select_sender_monitor,
    _sender_debug_state,
    _set_checkbox_value,
    _set_input_value,
    _set_select_value,
    _wait_for_ready_state,
    _wait_for_receiver_completion,
    _wait_for_receiver_devices,
    _wait_for_receiver_stream_ready,
)


def _parse_metric_float(value: str) -> float:
    token = value.strip().replace(",", ".").split()[0]
    return float(token.rstrip("s"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one real web-ui sender/receiver case")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mode", choices=["fountain", "sequential"], required=True)
    parser.add_argument("--bpc", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--fountain-redundancy", type=float, default=1.5)
    parser.add_argument("--fountain-auto-stop", action="store_true")
    parser.add_argument("--sequential-repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    base_url = args.base_url
    input_path = args.input.expanduser().resolve()
    input_bytes = input_path.read_bytes()

    response = requests.get(f"{base_url}/api/devices?force=1", timeout=60.0)
    response.raise_for_status()
    device = _select_capture_device(response.json())
    requests.post(
        f"{base_url}/api/devices/warm",
        json={"device": int(device["index"])},
        timeout=10.0,
    )

    receiver_monitor = _select_receiver_monitor()
    sender_monitor = _select_sender_monitor()
    receiver_height = max(900, min(1040, receiver_monitor.height))
    receiver_width = max(1200, min(1600, receiver_monitor.width))

    result: dict[str, object] = {}
    try:
        with _chrome_session(monitor=receiver_monitor, width=receiver_width, height=receiver_height) as receiver_driver:
            with _chrome_session(
                app_url=f"{base_url}/sender/app",
                monitor=sender_monitor,
                width=sender_monitor.width,
                height=sender_monitor.height,
            ) as sender_driver:
                receiver_driver.get(base_url)
                _wait_for_ready_state(receiver_driver)
                _position_window(receiver_driver, receiver_monitor, width=receiver_width, height=receiver_height)
                _wait_for_receiver_devices(receiver_driver)
                _set_select_value(receiver_driver, "deviceSelect", str(device["index"]))
                _set_select_value(receiver_driver, "profileSelect", "balanced")
                _set_select_value(receiver_driver, "modeSelect", args.mode)
                _set_select_value(receiver_driver, "bpcSelect", str(args.bpc))
                _set_select_value(receiver_driver, "previewQualitySelect", "45")

                _wait_for_ready_state(sender_driver, sentinel_id="fileInput")
                _position_window(sender_driver, sender_monitor, width=sender_monitor.width, height=sender_monitor.height)
                _set_select_value(sender_driver, "protocolSelect", args.mode)
                _set_select_value(sender_driver, "bpcSelect", str(args.bpc))
                _set_select_value(sender_driver, "profileSelect", "balanced")
                _set_select_value(sender_driver, "fpsModeSelect", "profile")
                if args.mode == "fountain":
                    _set_checkbox_value(sender_driver, "fountainAutoStopInput", args.fountain_auto_stop)
                    _set_input_value(sender_driver, "fountainRedundancyInput", f"{args.fountain_redundancy:.2f}")
                else:
                    _set_input_value(sender_driver, "sequentialRedundancyInput", str(args.sequential_repeat))
                sender_driver.find_element(By.ID, "fileInput").send_keys(str(input_path))
                time.sleep(2.0)
                _bring_to_front(sender_driver)
                _fullscreen_window(sender_driver, sender_monitor)

                receiver_driver.find_element(By.ID, "startBtn").click()
                _wait_for_receiver_stream_ready(receiver_driver)
                time.sleep(2.0)
                started = time.perf_counter()
                sender_driver.find_element(By.ID, "startBtn").click()
                try:
                    metrics = _wait_for_receiver_completion(
                        receiver_driver,
                        timeout_s=args.timeout,
                        sender_debug=_sender_debug_state(sender_driver),
                    )
                    elapsed = time.perf_counter() - started
                    received = _download_received_bytes(base_url, metrics["download"], timeout_s=60.0)
                    result = {
                        "ok": received == input_bytes,
                        "mode": args.mode,
                        "bpc": args.bpc,
                        "input": str(input_path),
                        "input_size_bytes": len(input_bytes),
                        "elapsed_s": elapsed,
                        "ui_duration_s": _parse_metric_float(metrics["duration"]),
                        "ui_speed_mbps": _parse_metric_float(metrics["speed"]),
                        "measured_speed_mbps": (len(input_bytes) * 8.0) / elapsed / 1_000_000.0,
                        "ui_name": metrics["name"],
                        "ui_sha": metrics["sha"],
                        "receiver_state": _receiver_debug_state(receiver_driver),
                        "sender_state": _sender_debug_state(sender_driver),
                    }
                except Exception as exc:
                    result = {
                        "ok": False,
                        "mode": args.mode,
                        "bpc": args.bpc,
                        "input": str(input_path),
                        "input_size_bytes": len(input_bytes),
                        "error": str(exc),
                        "receiver_state": _receiver_debug_state(receiver_driver),
                        "sender_state": _sender_debug_state(sender_driver),
                    }
                finally:
                    with contextlib.suppress(Exception):
                        sender_driver.execute_script(
                            "document.getElementById('stopBtn').click();"
                        )
    finally:
        with contextlib.suppress(Exception):
            _reset_receiver(base_url, int(device["index"]))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
