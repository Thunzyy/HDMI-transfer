from __future__ import annotations

import pytest

from hdmi_transfer.application.progress_estimate import (
    ProgressEstimator,
    fountain_droplets_needed,
)


def test_needed_droplets_follow_measured_decoder_overhead():
    # Small systems finish near K thanks to Gaussian elimination, large ones need ~20 % more.
    assert fountain_droplets_needed(100, unique=0) == 105
    assert fountain_droplets_needed(4000, unique=0) == 4800


def test_needed_droplets_grow_when_decoding_takes_longer_than_expected():
    # 120 unique droplets for K=100 and still not decoded: the end is near, not past.
    assert fountain_droplets_needed(100, unique=120) > 120


def test_progress_is_linear_in_received_units_not_in_decoded_chunks():
    estimator = ProgressEstimator()
    percent, _ = estimator.update(now=0.0, done=50, total=100, decoded_fraction=0.02)
    assert percent == 50.0


def test_progress_never_goes_backwards():
    estimator = ProgressEstimator()
    estimator.update(now=0.0, done=90, total=100)
    percent, _ = estimator.update(now=1.0, done=91, total=130)
    assert percent == 90.0


def test_decoded_fraction_wins_when_ahead():
    estimator = ProgressEstimator()
    percent, _ = estimator.update(now=0.0, done=10, total=100, decoded_fraction=0.6)
    assert percent == 60.0


def test_progress_stays_below_100_until_complete():
    estimator = ProgressEstimator()
    percent, _ = estimator.update(now=0.0, done=100, total=100)
    assert percent == 99.9


def test_eta_needs_a_measured_rate():
    estimator = ProgressEstimator()
    assert estimator.update(now=0.0, done=10, total=100)[1] == -1
    assert estimator.update(now=1.0, done=20, total=100)[1] == -1  # span < 2 s


def test_eta_uses_recent_rate_and_adapts_to_slowdowns():
    estimator = ProgressEstimator(window_s=10.0)
    for second in range(0, 11):
        _, eta = estimator.update(now=float(second), done=10 * second, total=1000)
    assert eta == pytest.approx(90.0)  # 900 left at 10/s

    # Rate drops to 1/s: after a full window the ETA reflects only the new rate.
    done = 100
    for second in range(11, 22):
        done += 1
        _, eta = estimator.update(now=float(second), done=done, total=1000)
    assert eta == pytest.approx(1000 - done, rel=0.01)


def test_reset_clears_history():
    estimator = ProgressEstimator()
    estimator.update(now=0.0, done=90, total=100)
    estimator.reset()
    assert estimator.update(now=5.0, done=1, total=100)[0] == 1.0
