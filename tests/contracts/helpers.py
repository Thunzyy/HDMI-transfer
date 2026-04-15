from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

from hdmi_transfer.core.config import (
    FRAME_TYPE_DATA,
    HEADER_SIZE,
    PROFILES,
    SEQ_HEADER_FMT,
    SEQ_HEADER_PRE_CRC,
    SEQ_MAGIC,
)
from hdmi_transfer.core.file_handling.metadata import (
    build_start_metadata,
    parse_fountain_metadata,
)
from hdmi_transfer.core.protocols.encoding import bytes_to_pixels
from hdmi_transfer.core.protocols.fountain import (
    FOUNT_HEADER_CURRENT_SIZE,
    FOUNT_MAGIC_V2,
    FountainProtocol,
)
from hdmi_transfer.core.protocols.sequential import (
    LEGACY_WEB_SEQ_MAGIC,
    SequentialProtocol,
)


@dataclass(frozen=True)
class SequentialContractFixture:
    header_size: int
    magic_hex: str
    payload_len: int


@dataclass(frozen=True)
class FountainContractFixture:
    header_size: int
    magic_hex: str
    max_frames: int | None


def _sample_frame_centers(frame: np.ndarray, *, block_size: int) -> np.ndarray:
    half = block_size // 2
    return frame[half::block_size, half::block_size, :]


def build_sequential_contract_fixture() -> SequentialContractFixture:
    profile = PROFILES["speed"]
    protocol = SequentialProtocol(profile=profile)
    payload = b"contract-payload" * 8

    frame = protocol.encode_start_frame("contract.bin", payload, total_data_frames=1)
    sampled = _sample_frame_centers(frame, block_size=profile.block_size)
    result = protocol.decode_frame(sampled)

    assert result.is_valid
    assert result.data is not None

    return SequentialContractFixture(
        header_size=HEADER_SIZE,
        magic_hex=f"{SEQ_MAGIC:04X}",
        payload_len=len(result.data),
    )


def build_fountain_contract_fixture() -> FountainContractFixture:
    profile = PROFILES["speed"]
    protocol = FountainProtocol(profile=profile)
    payload = bytes([0xAB]) * protocol.bytes_per_frame

    frame = protocol.encode_frame(
        payload,
        frame_index=7,
        total_frames=11,
        seed=7,
        expected_droplets=99,
    )
    sampled = _sample_frame_centers(frame, block_size=profile.block_size)
    result = protocol.decode_frame(sampled)

    assert result.is_valid

    return FountainContractFixture(
        header_size=FOUNT_HEADER_CURRENT_SIZE,
        magic_hex=f"{FOUNT_MAGIC_V2:04X}",
        max_frames=result.max_frames,
    )


def build_send_contract_fixture(mode: str) -> dict[str, object]:
    profile = PROFILES["speed"]
    payload = b"send-contract-payload" * 8

    if mode == "sequential":
        protocol = SequentialProtocol(profile=profile)
        start = protocol.decode_frame(
            _sample_frame_centers(
                protocol.encode_start_frame("contract.bin", payload, 1),
                block_size=profile.block_size,
            )
        )
        data = protocol.decode_frame(
            _sample_frame_centers(
                protocol.encode_frame(payload[:128], 0, 1),
                block_size=profile.block_size,
            )
        )
        end = protocol.decode_frame(
            _sample_frame_centers(
                protocol.encode_end_frame(1),
                block_size=profile.block_size,
            )
        )
        return {
            "mode": mode,
            "start_frame_type": start.frame_type,
            "data_frame_type": data.frame_type,
            "end_frame_type": end.frame_type,
        }

    if mode == "fountain":
        metadata = build_start_metadata("contract.bin", payload)
        wrapped = metadata + payload
        file_size, _, filename, _ = parse_fountain_metadata(wrapped)
        return {
            "mode": mode,
            "metadata_filename": filename,
            "metadata_file_size": file_size,
            "payload": payload,
        }

    raise ValueError(f"Unsupported mode: {mode}")


def build_receive_contract_fixture(mode: str) -> dict[str, object]:
    profile = PROFILES["speed"]

    if mode == "sequential":
        payload = b"legacy-sequential"
        header_pre_crc = struct.pack(
            SEQ_HEADER_FMT,
            LEGACY_WEB_SEQ_MAGIC,
            FRAME_TYPE_DATA,
            0,
            1,
            len(payload),
        )
        crc = zlib.crc32(header_pre_crc + payload) & 0xFFFFFFFF
        frame_bytes = header_pre_crc + struct.pack(">I", crc) + payload
        blocks_grid = bytes_to_pixels(
            frame_bytes,
            profile.blocks_per_frame,
            profile.rows,
            profile.cols,
            profile.bits_per_channel,
        )
        frame = np.repeat(
            np.repeat(blocks_grid, profile.block_size, axis=0),
            profile.block_size,
            axis=1,
        )[..., ::-1]

        result = SequentialProtocol(profile=profile).decode_frame(
            _sample_frame_centers(frame, block_size=profile.block_size)
        )
        return {
            "legacy_magic_valid": result.is_valid,
            "frame_type": result.frame_type,
        }

    if mode == "fountain":
        protocol = FountainProtocol(profile=profile)
        frame = protocol.encode_frame(
            b"\x42" * protocol.bytes_per_frame,
            frame_index=7,
            total_frames=11,
            seed=7,
            expected_droplets=13,
        )
        result = protocol.decode_frame(
            _sample_frame_centers(frame, block_size=profile.block_size)
        )
        return {
            "frame_index": result.frame_index,
            "total_frames": result.total_frames,
        }

    raise ValueError(f"Unsupported mode: {mode}")
