from dataclasses import replace

import numpy as np
import pytest
import cv2

from hdmi_transfer.adapters.calibration_store import CalibrationStore, calibration_key
from hdmi_transfer.application.preflight import build_calibration_frame
from hdmi_transfer.domain.models import ResolutionProfile
from hdmi_transfer.adapters.receive_worker import ReceiverWorker


PROFILE = ResolutionProfile("small", 160, 160, 8, 60, bits_per_channel=2)


def calibration_frames(profile=PROFILE, indices=range(3)):
    return [build_calibration_frame(profile, i) for i in indices]


class FiniteCapture:
    def __init__(self, worker, frames):
        self.worker, self.frames = worker, iter(frames)

    def read(self):
        try:
            return True, next(self.frames)
        except StopIteration:
            self.worker._stop_event.set()
            return False, None


def worker(tmp_path, **kwargs):
    return ReceiverWorker(device=0, profile=PROFILE, require_preflight=True,
                          device_identity="Test card",
                          calibration_store=CalibrationStore(tmp_path / "calibration.json"),
                          **kwargs)


def key(profile=PROFILE, capture_shape=(160, 160, 3)):
    return calibration_key(device_identity="Test card", open_device=0, backend=None,
                           profile=profile, capture_shape=capture_shape)


def test_first_calibration_saves_and_next_worker_validates_cached_geometry(tmp_path, monkeypatch):
    first = worker(tmp_path)
    frames = calibration_frames()
    assert first._wait_for_preflight(FiniteCapture(first, frames))
    assert first.get_runtime_state()["calibration_state"] == "saved"
    assert first._calibration_store.load(key()) == (0, 0, 1.0, 1.0)
    second = worker(tmp_path)
    assert second.get_runtime_state()["preflight_state"] != "ok"

    def unexpected_estimate(*args):
        raise AssertionError("Valid saved geometry must avoid dynamic image scanning")

    monkeypatch.setattr("hdmi_transfer.application.receive_geometry.estimate_sampling_from_frame", unexpected_estimate)
    assert second._wait_for_preflight(FiniteCapture(second, frames))
    assert second.get_runtime_state()["calibration_state"] == "reused"
    assert second.get_runtime_state()["calibration_samples"] == 3


def test_repeated_capture_of_single_sender_frame_cannot_validate_calibration(tmp_path):
    receiver = worker(tmp_path)
    same_frame = calibration_frames(indices=[7])[0]
    assert not receiver._wait_for_preflight(FiniteCapture(receiver, [same_frame] * 8))
    assert receiver.get_runtime_state()["preflight_state"] != "ok"
    assert not receiver._calibration_store.path.exists()


def test_stale_geometry_recovers_and_replaces_the_cached_hint(tmp_path):
    receiver = worker(tmp_path)
    assert receiver._calibration_store.save(key(), (16, 16, 0.6, 0.6))
    assert receiver._wait_for_preflight(FiniteCapture(receiver, calibration_frames()))
    assert receiver.get_runtime_state()["calibration_state"] == "saved"
    assert receiver._calibration_store.load(key()) == (0, 0, 1.0, 1.0)


def test_letterboxed_geometry_is_learned_then_reused_without_search(tmp_path, monkeypatch):
    frames = []
    for source in calibration_frames():
        frame = np.zeros_like(source)
        frame[8:152, 8:152] = cv2.resize(source, (144, 144), interpolation=cv2.INTER_NEAREST)
        frames.append(frame)
    first = worker(tmp_path)
    assert first._wait_for_preflight(FiniteCapture(first, frames * 20))
    saved = first._calibration_store.load(key())
    assert saved != (0, 0, 1.0, 1.0)
    second = worker(tmp_path)
    monkeypatch.setattr("hdmi_transfer.application.receive_geometry.estimate_sampling_from_frame",
                        lambda *args: pytest.fail("Cached letterbox must not trigger a search"))
    assert second._wait_for_preflight(FiniteCapture(second, frames))
    assert second.get_runtime_state()["calibration_reused"] is True


def test_recalibrate_ignores_saved_hint(tmp_path, monkeypatch):
    receiver = worker(tmp_path, force_recalibration=True)
    receiver._calibration_store.save(key(), (0, 0, 1.0, 1.0))
    monkeypatch.setattr(receiver._calibration_store, "load", lambda _: pytest.fail("Forced calibration read cache"))
    assert receiver._wait_for_preflight(FiniteCapture(receiver, calibration_frames()))
    assert receiver.get_runtime_state()["calibration_reused"] is False


def test_encoding_change_is_detected_and_requires_three_matching_frames(tmp_path):
    receiver = worker(tmp_path)
    frames = calibration_frames(indices=[0, 1]) + calibration_frames(
        replace(PROFILE, bits_per_channel=1), indices=[10, 11, 12],
    )
    assert receiver._wait_for_preflight(FiniteCapture(receiver, frames))
    assert receiver.get_runtime_state()["frames_captured"] == 5
    assert receiver.get_runtime_state()["transfer_bpc"] == 1
    assert receiver._calibration_store.load(key()) is None
    assert receiver._calibration_store.load(key(replace(PROFILE, bits_per_channel=1))) is not None


def test_failed_live_signal_never_trusts_a_saved_entry(tmp_path):
    receiver = worker(tmp_path)
    receiver._calibration_store.save(key(), (0, 0, 1.0, 1.0))
    blank = np.zeros((160, 160, 3), dtype=np.uint8)
    assert not receiver._wait_for_preflight(FiniteCapture(receiver, [blank] * 3))
    assert receiver.get_runtime_state()["preflight_state"] != "ok"


def test_preview_encoding_requires_a_consumer_and_can_be_disabled(tmp_path, monkeypatch):
    receiver = worker(tmp_path)
    encoded = []
    monkeypatch.setattr(receiver, "_publish_preview", lambda frame: encoded.append(frame))
    frame = calibration_frames()[0]
    receiver._maybe_publish_preview(frame)
    assert not encoded
    receiver.add_preview_consumer()
    receiver._maybe_publish_preview(frame)
    assert len(encoded) == 1
    receiver._preview_last_publish = 0
    receiver._preview_target_fps = 0
    receiver._maybe_publish_preview(frame)
    assert len(encoded) == 1
    receiver.remove_preview_consumer()
    assert receiver._preview_consumers == 0


def test_preview_disconnect_unregisters_its_consumer(tmp_path, monkeypatch):
    from hdmi_transfer.interfaces.web.app_factory import create_app

    app = create_app(output_dir=str(tmp_path), runtime=False)
    receiver = worker(tmp_path)
    app._receiver_worker = receiver
    monkeypatch.setattr(receiver, "is_alive", lambda: True)
    monkeypatch.setattr(receiver, "wait_for_preview", lambda *args, **kwargs: (b"jpeg", 1))
    response = app.test_client().get("/api/receive/preview", buffered=False)
    assert receiver._preview_consumers == 1
    response.close()
    assert receiver._preview_consumers == 0


def test_auto_detection_does_not_discard_the_first_payload_frame(tmp_path, monkeypatch):
    from hdmi_transfer.application.send_session import SendSession

    # A one-packet file must complete even when auto-detection consumes it first.
    source = tmp_path / "small.bin"
    source.write_bytes(b"hello")
    sender = SendSession.from_input(input_path=str(source), mode="fountain", profile=PROFILE)
    frame = next(sender.iter_frame_packets()).frame
    receiver = worker(tmp_path, mode="auto", output_dir=str(tmp_path))
    events = []
    original = receiver._publish
    monkeypatch.setattr(receiver, "_publish", lambda kind, data: (events.append((kind, data)), original(kind, data)))
    receiver._run_auto(FiniteCapture(receiver, [frame]))
    complete = next(data for kind, data in events if kind == "complete")
    assert complete["sha256_ok"] is True


def test_calibration_pattern_can_remain_visible_without_restarting_geometry_search(tmp_path, monkeypatch):
    receiver = worker(tmp_path, mode="fountain")
    frames = calibration_frames()
    assert receiver._wait_for_preflight(FiniteCapture(receiver, frames))
    monkeypatch.setattr("hdmi_transfer.application.receive_geometry.estimate_sampling_from_frame",
                        lambda *args: pytest.fail("A validated calibration tail must not trigger a search"))
    receiver._run_fountain(FiniteCapture(receiver, frames * 5))
    assert receiver.get_runtime_state()["state"] == "stopped"


def test_capture_size_change_clears_the_validated_geometry_hint(tmp_path):
    receiver = worker(tmp_path)
    assert receiver._wait_for_preflight(FiniteCapture(receiver, calibration_frames()))
    receiver._sampling = (8, 8, 0.9, 0.9)
    receiver._set_runtime_state(calibration_reused=True)
    receiver._ensure_size(np.zeros((320, 320, 3), dtype=np.uint8))
    assert receiver._sampling == (0, 0, 1.0, 1.0)
    assert receiver.get_runtime_state()["calibration_reused"] is False
    assert receiver.get_runtime_state()["calibration_state"] == "calibrating"


def test_auto_waiting_for_offline_confirmation_does_not_switch_capture_device(tmp_path, monkeypatch):
    from hdmi_transfer.application.send_session import SendSession

    receiver = worker(tmp_path, mode="auto", backend=int(cv2.CAP_DSHOW),
                      fallback_targets=[(1, int(cv2.CAP_MSMF))], output_dir=str(tmp_path))
    receiver._fallback_targets = [(1, int(cv2.CAP_MSMF))]
    frames = calibration_frames()
    assert receiver._wait_for_preflight(FiniteCapture(receiver, frames))
    source = tmp_path / "short.bin"
    source.write_bytes(b"confirmed after six seconds")
    sender = SendSession.from_input(input_path=str(source), mode="fountain", profile=PROFILE)
    payload = next(sender.iter_frame_packets()).frame
    events = []
    original = receiver._publish
    monkeypatch.setattr(receiver, "_publish", lambda kind, data: (events.append((kind, data)), original(kind, data)))
    receiver._run_auto(FiniteCapture(receiver, frames * 120 + [payload]))
    complete = next(data for kind, data in events if kind == "complete")
    assert complete["sha256_ok"] is True
    assert not any(data.get("state") == "fallback" for _, data in events)


def test_auto_replays_original_capture_size_without_invalidating_calibration(tmp_path):
    from hdmi_transfer.application.send_session import SendSession

    receiver = worker(tmp_path, mode="auto", output_dir=str(tmp_path))
    raw_frames = [cv2.resize(frame, (320, 320), interpolation=cv2.INTER_NEAREST)
                  for frame in calibration_frames()]
    assert receiver._wait_for_preflight(FiniteCapture(receiver, raw_frames))
    source = tmp_path / "source.bin"
    source.write_bytes(b"raw capture dimensions survive auto-detection")
    sender = SendSession.from_input(input_path=str(source), mode="fountain", profile=PROFILE)
    raw_payload = cv2.resize(next(sender.iter_frame_packets()).frame, (320, 320),
                            interpolation=cv2.INTER_NEAREST)
    receiver._run_auto(FiniteCapture(receiver, [raw_payload]))
    state = receiver.get_runtime_state()
    assert state["state"] == "complete"
    assert state["sha256_ok"] is True
    assert state["calibration_state"] == "saved"
    assert receiver._calibration_capture_shape == (320, 320)


def test_worker_never_saves_calibration_with_a_corrupt_4k_tail(tmp_path):
    from hdmi_transfer.core.config import PROFILES

    profile = replace(PROFILES["quality"], bits_per_channel=2)
    receiver = ReceiverWorker(device=0, profile=profile, require_preflight=True,
                              calibration_store=CalibrationStore(tmp_path / "calibration.json"))
    frames = []
    for index in range(3):
        frame = build_calibration_frame(profile, index)
        frame[-8:, -8:] = 255 - frame[-8:, -8:]
        frames.append(frame)
    assert not receiver._wait_for_preflight(FiniteCapture(receiver, frames))
    assert receiver.get_runtime_state()["preflight_state"] != "ok"
    assert not receiver._calibration_store.path.exists()
