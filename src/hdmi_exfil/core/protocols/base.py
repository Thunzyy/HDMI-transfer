"""Abstract base class for encoding protocols and shared result types.

This module defines the contract that every encoding protocol must fulfil.
It is intentionally config-agnostic -- concrete protocols import grid
dimensions from ``hdmi_exfil.core.config`` themselves.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class FrameResult:
    """Structured result of a single frame decode attempt.

    Attributes:
        data: Decoded payload bytes, or ``None`` on failure.
        frame_type: Protocol-specific frame type tag (e.g. START/DATA/END).
        frame_index: Zero-based frame sequence number.
        total_frames: Total number of frames in the transfer.
        is_valid: ``True`` if the frame passed integrity checks (magic + CRC).
    """

    data: bytes | None
    frame_type: int | None
    frame_index: int | None
    total_frames: int | None
    is_valid: bool


class EncodingProtocol(ABC):
    """Interface that every encoding protocol must implement."""

    @abstractmethod
    def encode_frame(
        self,
        data: bytes,
        frame_index: int,
        total_frames: int,
        **kwargs: object,
    ) -> np.ndarray:
        """Encode *data* into a full-resolution frame image.

        Returns:
            A ``(HEIGHT, WIDTH, 3)`` uint8 NumPy array ready for display.
        """

    @abstractmethod
    def decode_frame(self, sampled_grid: np.ndarray) -> FrameResult:
        """Decode a sampled block grid into a ``FrameResult``.

        Args:
            sampled_grid: A ``(ROWS, COLS, 3)`` uint8 array of block centres.

        Returns:
            A ``FrameResult`` with ``is_valid=False`` on any decode failure.
        """

    @property
    @abstractmethod
    def bytes_per_frame(self) -> int:
        """Maximum payload bytes that fit in a single frame."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable protocol name (e.g. ``'sequential'``, ``'fountain'``)."""
