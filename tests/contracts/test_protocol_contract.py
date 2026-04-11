from __future__ import annotations

from tests.contracts.helpers import (
    build_fountain_contract_fixture,
    build_sequential_contract_fixture,
)


def test_sequential_start_frame_contract() -> None:
    contract = build_sequential_contract_fixture()

    assert contract.header_size == 17
    assert contract.magic_hex == "DA7A"
    assert contract.payload_len > 0


def test_fountain_frame_contract() -> None:
    contract = build_fountain_contract_fixture()

    assert contract.header_size == 16
    assert contract.magic_hex == "F0C1"
    assert contract.max_frames == 99
