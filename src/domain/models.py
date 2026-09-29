"""Shared immutable models for the HDMI Transfer domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


SEQUENTIAL_HEADER_SIZE = 17
FOUNTAIN_HEADER_SIZE = 16


@dataclass(frozen=True)
class ResolutionProfile:
    """Immutable bundle of resolution and encoding parameters."""

    SEQUENTIAL_HEADER_SIZE: ClassVar[int] = SEQUENTIAL_HEADER_SIZE
    FOUNTAIN_HEADER_SIZE: ClassVar[int] = FOUNTAIN_HEADER_SIZE

    name: str
    width: int
    height: int
    block_size: int
    target_fps: int
    bits_per_channel: int = 1

    @property
    def cols(self) -> int:
        return self.width // self.block_size

    @property
    def rows(self) -> int:
        return self.height // self.block_size

    @property
    def blocks_per_frame(self) -> int:
        return self.cols * self.rows

    @property
    def bits_per_frame(self) -> int:
        return self.blocks_per_frame * 3 * self.bits_per_channel

    @property
    def seq_bytes_per_frame(self) -> int:
        return (self.bits_per_frame // 8) - self.SEQUENTIAL_HEADER_SIZE

    @property
    def fount_header_size(self) -> int:
        return self.FOUNTAIN_HEADER_SIZE

    @property
    def fount_bytes_per_frame(self) -> int:
        return (self.bits_per_frame // 8) - self.FOUNTAIN_HEADER_SIZE


@dataclass(frozen=True)
class SequentialSpec:
    magic: int
    header_format: str
    header_pre_crc: int
    crc_size: int
    header_size: int


@dataclass(frozen=True)
class FountainSpec:
    magic: int
    current_magic: int
    header_pre_crc: int
    header_size: int


@dataclass(frozen=True)
class ProtocolManifest:
    width: int
    height: int
    block_size: int
    threshold: int
    profiles: dict[str, ResolutionProfile]
    sequential: SequentialSpec
    fountain: FountainSpec
