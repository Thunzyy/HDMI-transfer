"""Sequential encoding protocol -- first concrete EncodingProtocol.

Wraps the existing sequential encode/decode logic from sender.py and
receiver.py behind the :class:`EncodingProtocol` ABC interface.  Also
exposes START/END frame helpers and a :class:`TransferState` enum for
the sequential transfer lifecycle.
"""

from __future__ import annotations

import struct
import zlib
from enum import Enum, auto

import numpy as np

from hdmi_exfil.core.config import (
    DEFAULT_PROFILE,
    FRAME_TYPE_DATA,
    FRAME_TYPE_END,
    FRAME_TYPE_START,
    HEADER_SIZE,
    ResolutionProfile,
    SEQ_HEADER_FMT,
    SEQ_HEADER_PRE_CRC,
    SEQ_MAGIC,
)
from hdmi_exfil.core.file_handling.metadata import build_start_metadata
from hdmi_exfil.core.protocols.base import EncodingProtocol, FrameResult


class TransferState(Enum):
    """Sequential transfer lifecycle states."""

    START_PENDING = auto()
    RECEIVING = auto()
    COMPLETE = auto()


class SequentialProtocol(EncodingProtocol):
    """Concrete protocol for sequential frame-by-frame data transfer.

    This implementation mirrors the encoding logic in ``sender.py``
    (``encode_frame``) and the decoding logic in ``receiver.py``
    (``decode_frame_full``) exactly, wrapped behind the
    :class:`EncodingProtocol` ABC.

    Parameters
    ----------
    profile:
        Optional ``ResolutionProfile`` controlling spatial dimensions and
        capacity.  Defaults to ``DEFAULT_PROFILE`` (1080p/240fps) for full
        backward compatibility.
    """

    def __init__(self, profile: ResolutionProfile | None = None) -> None:
        self._profile = profile or DEFAULT_PROFILE

    # ------------------------------------------------------------------
    # ABC properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        """Human-readable protocol name."""
        return "sequential"

    @property
    def bytes_per_frame(self) -> int:
        """Maximum payload bytes per frame."""
        return self._profile.seq_bytes_per_frame

    # ------------------------------------------------------------------
    # ABC methods
    # ------------------------------------------------------------------

    def encode_frame(
        self,
        data: bytes,
        frame_index: int,
        total_frames: int,
        *,
        frame_type: int = FRAME_TYPE_DATA,
        **kwargs: object,
    ) -> np.ndarray:
        """Encode *data* into a full-resolution frame image.

        Logic is identical to ``sender.py:encode_frame`` (lines 59-104)
        except the terminal progress output is omitted (UI concern).
        """
        # Build pre-CRC header
        header_pre_crc = struct.pack(
            SEQ_HEADER_FMT,
            SEQ_MAGIC,
            frame_type,
            frame_index,
            total_frames,
            len(data),
        )

        # CRC32 over header + payload
        crc = zlib.crc32(header_pre_crc + data) & 0xFFFFFFFF
        crc_bytes = struct.pack(">I", crc)

        full_data = header_pre_crc + crc_bytes + data

        # Convert bytes to bits
        byte_arr = np.frombuffer(full_data, dtype=np.uint8)
        bits = np.unpackbits(byte_arr)

        # Pad bits to frame capacity (blocks_per_frame * 3)
        total_bits_needed = self._profile.blocks_per_frame * 3
        padding_needed = total_bits_needed - len(bits)
        if padding_needed > 0:
            bits = np.pad(bits, (0, padding_needed), "constant")

        # Reshape to (blocks_per_frame, 3) -> RGB values per block
        pixel_bits = bits.reshape((self._profile.blocks_per_frame, 3))

        # Map 0 -> 0, 1 -> 255
        pixel_values = pixel_bits * 255

        # Reshape to grid (rows, cols, 3) and upscale
        blocks_grid = pixel_values.reshape(
            (self._profile.rows, self._profile.cols, 3),
        ).astype(np.uint8)
        img = np.repeat(
            np.repeat(blocks_grid, self._profile.block_size, axis=0),
            self._profile.block_size,
            axis=1,
        )
        # Safety trim to exact profile dimensions
        img = img[: self._profile.height, : self._profile.width, :]

        return img

    def decode_frame(self, sampled_grid: np.ndarray) -> FrameResult:
        """Decode a sampled block grid into a :class:`FrameResult`.

        Logic mirrors ``receiver.py:decode_frame_full`` (lines 97-134)
        with threshold ``> 128``.
        """
        flat_pixels = sampled_grid.reshape(-1, 3)

        # Threshold: > 128 is 1, else 0
        bits = (flat_pixels > 128).astype(np.uint8)
        flat_bits = bits.reshape(-1)

        # Pack bits into bytes
        packed_bytes = np.packbits(flat_bits)
        frame_bytes = packed_bytes.tobytes()

        # Need at least full header (17 bytes)
        if len(frame_bytes) < HEADER_SIZE:
            return FrameResult(
                data=None,
                frame_type=None,
                frame_index=None,
                total_frames=None,
                is_valid=False,
            )

        # Parse pre-CRC header fields
        try:
            magic, frame_type, frame_index, total_frames, data_len = struct.unpack(
                SEQ_HEADER_FMT, frame_bytes[:SEQ_HEADER_PRE_CRC]
            )
        except struct.error:
            return FrameResult(
                data=None,
                frame_type=None,
                frame_index=None,
                total_frames=None,
                is_valid=False,
            )

        # Magic number check
        if magic != SEQ_MAGIC:
            return FrameResult(
                data=None,
                frame_type=None,
                frame_index=None,
                total_frames=None,
                is_valid=False,
            )

        # Extract stored CRC
        stored_crc = struct.unpack(
            ">I", frame_bytes[SEQ_HEADER_PRE_CRC:HEADER_SIZE]
        )[0]

        # Sanity check on data_len
        if data_len > self._profile.seq_bytes_per_frame or data_len == 0:
            return FrameResult(
                data=None,
                frame_type=None,
                frame_index=None,
                total_frames=None,
                is_valid=False,
            )

        # Extract payload
        payload = frame_bytes[HEADER_SIZE : HEADER_SIZE + data_len]

        # Verify CRC32 (over pre-CRC header + payload)
        computed_crc = (
            zlib.crc32(frame_bytes[:SEQ_HEADER_PRE_CRC] + payload) & 0xFFFFFFFF
        )
        if computed_crc != stored_crc:
            return FrameResult(
                data=None,
                frame_type=None,
                frame_index=None,
                total_frames=None,
                is_valid=False,
            )

        return FrameResult(
            data=payload,
            frame_type=frame_type,
            frame_index=frame_index,
            total_frames=total_frames,
            is_valid=True,
        )

    # ------------------------------------------------------------------
    # Sequential-specific helpers (not part of ABC)
    # ------------------------------------------------------------------

    def encode_start_frame(
        self,
        filename: str,
        file_data: bytes,
        total_data_frames: int,
    ) -> np.ndarray:
        """Encode a START frame with file metadata.

        Uses :func:`~hdmi_exfil.core.file_handling.metadata.build_start_metadata`
        to construct the payload, then encodes via :meth:`encode_frame` with
        ``frame_type=FRAME_TYPE_START``.
        """
        metadata = build_start_metadata(filename, file_data)
        return self.encode_frame(
            metadata,
            0,
            total_data_frames,
            frame_type=FRAME_TYPE_START,
        )

    def encode_end_frame(self, total_data_frames: int) -> np.ndarray:
        """Encode an END frame signaling transfer completion."""
        return self.encode_frame(
            b"\x00",
            total_data_frames,
            total_data_frames,
            frame_type=FRAME_TYPE_END,
        )

    def decode_frame_legacy(
        self, sampled_grid: np.ndarray
    ) -> tuple[int, int, bytes, int] | tuple[None, None, None, None]:
        """Decode returning the old 4-tuple for backward compatibility.

        Returns ``(frame_index, total_frames, data, data_len)`` or
        ``(None, None, None, None)`` on failure.
        """
        result = self.decode_frame(sampled_grid)
        if not result.is_valid:
            return None, None, None, None
        assert result.data is not None  # guaranteed by is_valid
        return (
            result.frame_index,
            result.total_frames,
            result.data,
            len(result.data),
        )
