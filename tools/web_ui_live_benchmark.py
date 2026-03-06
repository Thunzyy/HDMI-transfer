from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True)
class BenchmarkCase:
    label: str
    mode: str
    bits_per_channel: int
    fountain_redundancy: float = 1.5
    fountain_auto_stop: bool = True
    sequential_repeat: int = 1


@dataclass
class BenchmarkResult:
    label: str
    mode: str
    bits_per_channel: int
    file_size_bytes: int
    duration_s: float
    ui_duration_s: float
    ui_speed_mbps: float
    measured_speed_mbps: float
    ui_name: str
    ui_sha: str
    ok: bool
    error: str = ""


def _parse_metric_float(value: str) -> float:
    token = value.strip().replace(",", ".").split()[0]
    return float(token.rstrip("s"))


def _write_results(
    output_path: Path,
    *,
    input_path: Path,
    results: list[BenchmarkResult],
) -> None:
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input_path": str(input_path),
        "input_size_bytes": input_path.stat().st_size,
        "results": [asdict(item) for item in results],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _default_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase("fountain_bpc2_r1.50", "fountain", 2, fountain_redundancy=1.50),
        BenchmarkCase("fountain_bpc3_r1.25", "fountain", 3, fountain_redundancy=1.25),
        BenchmarkCase("fountain_bpc3_r1.50", "fountain", 3, fountain_redundancy=1.50),
        BenchmarkCase("fountain_bpc3_r2.00", "fountain", 3, fountain_redundancy=2.00),
        BenchmarkCase("sequential_bpc2_rep1", "sequential", 2, sequential_repeat=1),
        BenchmarkCase("sequential_bpc3_rep1", "sequential", 3, sequential_repeat=1),
        BenchmarkCase("sequential_bpc3_rep2", "sequential", 3, sequential_repeat=2),
        BenchmarkCase("sequential_bpc3_rep3", "sequential", 3, sequential_repeat=3),
    ]


def _select_cases(all_cases: list[BenchmarkCase], labels: list[str] | None) -> list[BenchmarkCase]:
    if not labels:
        return all_cases
    wanted = {label.strip() for label in labels if label.strip()}
    selected = [case for case in all_cases if case.label in wanted]
    missing = sorted(wanted - {case.label for case in selected})
    if missing:
        raise SystemExit(f"unknown labels: {', '.join(missing)}")
    return selected


def _upload_sender_file(sender_driver, input_path: Path) -> None:
    sender_driver.find_element(By.ID, "fileInput").send_keys(str(input_path))
    deadline = time.time() + 60.0
    while time.time() < deadline:
        if sender_driver.find_element(By.ID, "fileName").text.strip() == input_path.name:
            return
        time.sleep(0.25)
    raise AssertionError(f"sender never loaded {input_path.name}")


def _configure_sender(sender_driver, *, base_url: str, case: BenchmarkCase, input_path: Path) -> None:
    _wait_for_ready_state(sender_driver, sentinel_id="fileInput")
    _set_select_value(sender_driver, "protocolSelect", case.mode)
    _set_select_value(sender_driver, "bpcSelect", str(case.bits_per_channel))
    _set_select_value(sender_driver, "profileSelect", "balanced")
    _set_select_value(sender_driver, "fpsModeSelect", "profile")
    if case.mode == "fountain":
        _set_checkbox_value(sender_driver, "fountainAutoStopInput", case.fountain_auto_stop)
        _set_input_value(sender_driver, "fountainRedundancyInput", f"{case.fountain_redundancy:.2f}")
    else:
        _set_input_value(sender_driver, "sequentialRedundancyInput", str(case.sequential_repeat))
    _upload_sender_file(sender_driver, input_path)


def _run_case(
    *,
    base_url: str,
    device_index: int,
    input_path: Path,
    input_bytes: bytes,
    case: BenchmarkCase,
) -> BenchmarkResult:
    receiver_monitor = _select_receiver_monitor()
    sender_monitor = _select_sender_monitor()
    receiver_height = max(900, min(1040, receiver_monitor.height))
    receiver_width = max(1200, min(1600, receiver_monitor.width))

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
                _position_window(
                    receiver_driver,
                    receiver_monitor,
                    width=receiver_width,
                    height=receiver_height,
                )
                _wait_for_receiver_devices(receiver_driver)
                _set_select_value(receiver_driver, "deviceSelect", str(device_index))
                _set_select_value(receiver_driver, "profileSelect", "balanced")
                _set_select_value(receiver_driver, "modeSelect", case.mode)
                _set_select_value(receiver_driver, "bpcSelect", str(case.bits_per_channel))
                _set_select_value(receiver_driver, "previewQualitySelect", "45")

                _position_window(
                    sender_driver,
                    sender_monitor,
                    width=sender_monitor.width,
                    height=sender_monitor.height,
                )
                _configure_sender(sender_driver, base_url=base_url, case=case, input_path=input_path)
                _bring_to_front(sender_driver)
                _fullscreen_window(sender_driver, sender_monitor)

                receiver_driver.find_element(By.ID, "startBtn").click()
                _wait_for_receiver_stream_ready(receiver_driver)
                time.sleep(2.0)

                started = time.perf_counter()
                sender_driver.find_element(By.ID, "startBtn").click()
                metrics = _wait_for_receiver_completion(
                    receiver_driver,
                    timeout_s=900.0,
                    sender_debug=_sender_debug_state(sender_driver),
                )
                duration_s = time.perf_counter() - started

                with contextlib.suppress(Exception):
                    sender_driver.execute_script(
                        "window.stopSending ? window.stopSending() : null;"
                    )
                with contextlib.suppress(Exception):
                    sender_driver.execute_script(
                        "document.getElementById('stopBtn').click();"
                    )

                received = _download_received_bytes(base_url, metrics["download"], timeout_s=60.0)
                if received != input_bytes:
                    raise AssertionError(f"{case.label}: downloaded bytes mismatch")

                ui_duration_s = _parse_metric_float(metrics["duration"])
                ui_speed_mbps = _parse_metric_float(metrics["speed"])
                measured_speed_mbps = (len(input_bytes) * 8.0) / duration_s / 1_000_000.0
                return BenchmarkResult(
                    label=case.label,
                    mode=case.mode,
                    bits_per_channel=case.bits_per_channel,
                    file_size_bytes=len(input_bytes),
                    duration_s=duration_s,
                    ui_duration_s=ui_duration_s,
                    ui_speed_mbps=ui_speed_mbps,
                    measured_speed_mbps=measured_speed_mbps,
                    ui_name=metrics["name"],
                    ui_sha=metrics["sha"],
                    ok=True,
                    error="",
                )
    except Exception as exc:
        raise AssertionError(
            f"{case.label} failed: {exc}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            _reset_receiver(base_url, device_index)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the live 5000 web UI sender/receiver")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "web_ui_live_benchmark_results.json")
    parser.add_argument("--labels", nargs="*")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    all_cases = _default_cases()
    if args.list:
        for case in all_cases:
            print(case.label)
        return

    input_path = args.input.expanduser().resolve()
    input_bytes = input_path.read_bytes()
    cases = _select_cases(all_cases, args.labels)

    response = requests.get(f"{args.base_url}/api/devices?force=1", timeout=60.0)
    response.raise_for_status()
    device = _select_capture_device(response.json())
    requests.post(
        f"{args.base_url}/api/devices/warm",
        json={"device": int(device["index"])},
        timeout=10.0,
    )

    results: list[BenchmarkResult] = []
    for case in cases:
        print(f"[bench] {case.label}", flush=True)
        started = time.perf_counter()
        try:
            result = _run_case(
                base_url=args.base_url,
                device_index=int(device["index"]),
                input_path=input_path,
                input_bytes=input_bytes,
                case=case,
            )
        except Exception as exc:
            result = BenchmarkResult(
                label=case.label,
                mode=case.mode,
                bits_per_channel=case.bits_per_channel,
                file_size_bytes=len(input_bytes),
                duration_s=time.perf_counter() - started,
                ui_duration_s=0.0,
                ui_speed_mbps=0.0,
                measured_speed_mbps=0.0,
                ui_name="",
                ui_sha="",
                ok=False,
                error=str(exc),
            )
        results.append(result)
        _write_results(args.output, input_path=input_path, results=results)
        if result.ok:
            print(
                f"[bench] done {case.label}: ui={result.ui_speed_mbps:.2f} Mbps "
                f"measured={result.measured_speed_mbps:.2f} Mbps "
                f"ui_name={result.ui_name} sha={result.ui_sha}",
                flush=True,
            )
        else:
            print(f"[bench] failed {case.label}: {result.error}", flush=True)

    print(args.output)


if __name__ == "__main__":
    main()
