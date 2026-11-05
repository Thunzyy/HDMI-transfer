from dataclasses import replace
import json

import pytest

from hdmi_transfer.adapters.calibration_store import CalibrationStore, calibration_key
from hdmi_transfer.domain.models import ResolutionProfile


PROFILE = ResolutionProfile("small", 160, 80, 8, 60, bits_per_channel=2)


def key(**overrides):
    values = dict(device_identity="Card A", open_device=0, backend=1400,
                  profile=PROFILE, capture_shape=(80, 160, 3))
    return calibration_key(**(values | overrides))


def test_store_roundtrip_and_configuration_separation(tmp_path):
    path = tmp_path / "state" / "calibration.json"
    assert CalibrationStore(path).load(key()) is None
    assert CalibrationStore(path).save(key(), (8, 4, 0.9, 0.8))
    assert CalibrationStore(path).load(key()) == (8, 4, 0.9, 0.8)
    for override in (
        {"device_identity": "Card B"}, {"open_device": 1}, {"backend": 700},
        {"profile": replace(PROFILE, bits_per_channel=1)},
        {"profile": replace(PROFILE, target_fps=30)}, {"capture_shape": (40, 80, 3)},
    ):
        assert CalibrationStore(path).load(key(**override)) is None
    assert not list(path.parent.glob(".calibration-*.tmp"))


@pytest.mark.parametrize("content", ["broken", "null", "[]", '{"version":999}',
    '{"version":1,"entries":[]}', '{"version":1,"entries":{"bad":null}}'])
def test_corrupt_store_is_ignored_and_can_be_replaced(tmp_path, content):
    path = tmp_path / "calibration.json"
    path.write_text(content)
    store = CalibrationStore(path)
    assert store.load("bad") is None
    assert store.save("good", (0, 0, 1.0, 1.0))
    assert CalibrationStore(path).load("good") == (0, 0, 1.0, 1.0)


@pytest.mark.parametrize("sampling", [[0, 0, 0, 1], [-1, 0, 1, 1],
    [0, 0, float("nan"), 1], [0, 0, float("inf"), 1], ["0", 0, 1, 1],
    [True, 0, 1, 1], [10**400, 0, 1, 1]])
def test_invalid_geometry_is_never_loaded_or_saved(tmp_path, sampling):
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"version": 1, "entries": {"bad": {"sampling": sampling}}}))
    store = CalibrationStore(path)
    assert store.load("bad") is None
    assert not store.save("bad", sampling)


def test_unwritable_store_is_nonfatal(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file")
    store = CalibrationStore(blocker / "calibration.json")
    assert store.load("key") is None
    assert not store.save("key", (0, 0, 1.0, 1.0))
