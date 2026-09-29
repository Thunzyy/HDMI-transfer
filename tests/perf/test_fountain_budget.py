from __future__ import annotations

import pytest

from hdmi_transfer.core.protocols.fountain_tuning import DEFAULT_FOUNTAIN_TUNING
from tests.test_fountain_overhead import measure_overhead


def test_fountain_budget_k100() -> None:
    avg_overhead, _, _, _ = measure_overhead(K=100, runs=20, max_multiplier=5)
    assert avg_overhead < DEFAULT_FOUNTAIN_TUNING.max_avg_overhead


@pytest.mark.slow
def test_fountain_budget_k500() -> None:
    avg_overhead, _, _, _ = measure_overhead(K=500, runs=20, max_multiplier=5)
    assert avg_overhead < DEFAULT_FOUNTAIN_TUNING.max_avg_overhead


@pytest.mark.slow
def test_fountain_budget_k1000() -> None:
    avg_overhead, _, _, _ = measure_overhead(K=1000, runs=10, max_multiplier=5)
    assert avg_overhead < DEFAULT_FOUNTAIN_TUNING.max_avg_overhead
