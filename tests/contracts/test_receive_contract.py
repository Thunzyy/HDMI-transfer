from __future__ import annotations

from tests.contracts.helpers import build_receive_contract_fixture


def test_sequential_receive_contract_accepts_legacy_magic() -> None:
    contract = build_receive_contract_fixture("sequential")

    assert contract["legacy_magic_valid"] is True
    assert contract["frame_type"] == 0x02


def test_fountain_receive_contract_uses_seed_as_frame_index() -> None:
    contract = build_receive_contract_fixture("fountain")

    assert contract["frame_index"] == 7
    assert contract["total_frames"] == 11
