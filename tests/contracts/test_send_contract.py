from __future__ import annotations

from tests.contracts.helpers import build_send_contract_fixture


def test_sequential_send_contract_uses_start_data_end_cycle() -> None:
    contract = build_send_contract_fixture("sequential")

    assert contract["mode"] == "sequential"
    assert contract["start_frame_type"] == 0x01
    assert contract["data_frame_type"] == 0x02
    assert contract["end_frame_type"] == 0x03


def test_fountain_send_contract_wraps_metadata_before_payload() -> None:
    contract = build_send_contract_fixture("fountain")

    assert contract["mode"] == "fountain"
    assert contract["metadata_filename"] == "contract.bin"
    assert contract["metadata_file_size"] == len(contract["payload"])
