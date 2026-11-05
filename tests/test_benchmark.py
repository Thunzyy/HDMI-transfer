from __future__ import annotations

import json
from dataclasses import replace

import pytest

from hdmi_transfer.core.cli import benchmark
from hdmi_transfer.domain.models import ResolutionProfile


@pytest.fixture
def profile():
    return ResolutionProfile("test", 320, 240, 8, 60, bits_per_channel=2)


@pytest.mark.parametrize("mode", ["sequential", "fountain"])
@pytest.mark.parametrize("bpc", [1, 2, 3])
def test_roundtrip_reports_only_verified_payload_bytes(profile, mode, bpc):
    result = benchmark.run_benchmark(
        replace(profile, bits_per_channel=bpc), mode, payload_size_kb=10,
    )

    assert result.completed
    assert result.integrity_ok
    assert not result.timed_out
    assert result.payload_bytes == result.total_bytes == 10 * 1024
    assert result.bytes_per_sec > 0
    assert result.error_rate == 0
    assert result.warmup_duration_sec >= 0


@pytest.mark.parametrize("mode", ["sequential", "fountain"])
def test_deadline_applies_to_both_protocols(profile, mode, monkeypatch):
    monkeypatch.setattr(benchmark, "_warmup_protocol", lambda *args: 0.25)
    clock = iter([0.0, 2.0, 2.0])
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(clock))

    result = benchmark.run_benchmark(profile, mode, duration_sec=1.0)

    assert result.timed_out
    assert not result.completed
    assert not result.integrity_ok
    assert result.total_frames == result.total_bytes == 0
    assert result.bytes_per_sec == 0
    assert result.payload_bytes == 100 * 1024
    assert result.duration_sec == 2.0
    assert result.warmup_duration_sec == 0.25


def test_fountain_checks_reconstructed_bytes_not_only_frame_crc(profile, monkeypatch):
    from hdmi_transfer.core.protocols.fountain import FountainDecoder

    original = FountainDecoder.get_file_data

    def corrupt_file(self):
        payload = original(self)
        return bytes([payload[0] ^ 1]) + payload[1:]

    monkeypatch.setattr(FountainDecoder, "get_file_data", corrupt_file)
    result = benchmark.run_benchmark(profile, "fountain", payload_size_kb=1)

    assert result.completed
    assert result.error_rate == 0
    assert not result.integrity_ok
    assert result.total_bytes == result.bytes_per_sec == 0


def test_sequential_checks_reconstructed_bytes(profile, monkeypatch):
    from hdmi_transfer.core.protocols.sequential import SequentialProtocol

    original = SequentialProtocol.decode_frame

    def corrupt_frame(self, sampled):
        result = original(self, sampled)
        if result.is_valid and result.data:
            result = replace(result, data=bytes([result.data[0] ^ 1]) + result.data[1:])
        return result

    monkeypatch.setattr(SequentialProtocol, "decode_frame", corrupt_frame)
    result = benchmark.run_benchmark(profile, "sequential", payload_size_kb=1)

    assert result.completed
    assert not result.integrity_ok
    assert result.error_rate == 1
    assert result.total_bytes == result.bytes_per_sec == 0


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_invalid_duration_rejected_before_work(profile, duration, monkeypatch):
    monkeypatch.setattr(benchmark, "_warmup_protocol", lambda *args: pytest.fail("unexpected work"))
    with pytest.raises(ValueError, match="finite positive"):
        benchmark.run_benchmark(profile, "fountain", duration_sec=duration)


@pytest.mark.parametrize("size", [0, -1, 1.5, True])
def test_invalid_payload_size_rejected_before_work(profile, size, monkeypatch):
    monkeypatch.setattr(benchmark, "_warmup_protocol", lambda *args: pytest.fail("unexpected work"))
    with pytest.raises(ValueError, match="positive integer"):
        benchmark.run_benchmark(profile, "fountain", payload_size_kb=size)


@pytest.mark.parametrize("failure", ["incomplete", "corrupt", "timed_out"])
def test_cli_exits_unsuccessfully_when_file_not_verified_in_time(monkeypatch, capsys, failure):
    result = benchmark.BenchmarkResult(
        profile="balanced", mode="fountain", frames_per_sec=1,
        bytes_per_sec=0, overhead_pct=0, error_rate=0, duration_sec=1,
        total_frames=1, total_bytes=0, completed=failure != "incomplete",
        integrity_ok=failure == "timed_out", timed_out=failure == "timed_out",
    )
    monkeypatch.setattr(benchmark, "run_benchmark", lambda *args: result)
    monkeypatch.setattr(benchmark.sys, "argv", ["hdmi-bench"])

    with pytest.raises(SystemExit) as exc:
        benchmark.main()

    assert exc.value.code == 1
    reported = json.loads(capsys.readouterr().out)
    assert reported["completed"] == result.completed
    assert reported["integrity_ok"] == result.integrity_ok
    assert reported["timed_out"] == result.timed_out


@pytest.mark.parametrize("args", [["--duration", "0"], ["--size", "-1"], ["--duration", "nan"]])
def test_cli_rejects_invalid_inputs(args):
    with pytest.raises(SystemExit) as exc:
        benchmark._build_parser().parse_args(args)
    assert exc.value.code == 2
