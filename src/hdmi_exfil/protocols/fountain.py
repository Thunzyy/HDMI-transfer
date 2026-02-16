"""Fountain-code (LT-code) encoding protocol implementation.

Implements FountainProtocol (3-bit-per-block RGB binary encoding with LT-code
redundancy) and FountainDecoder (belief-propagation / peeling decoder) behind
the ``EncodingProtocol`` ABC defined in ``base.py``.

Each block encodes 3 bits (one per R/G/B channel, each either 0 or 255),
matching the same 3bpp pattern used by SequentialProtocol.  This gives
12,150 bytes per frame (12,138 payload) -- a 3x capacity increase over the
original 1bpp (4,050 bytes / 4,038 payload) encoding.

Migrated from the monolithic ``receiver_fountain.py`` -- all logic is
functionally identical, but now uses the shared ``hdmi_exfil.prng.PRNG``
class and the canonical ``hdmi_exfil.config`` constants.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

from hdmi_exfil import config
from hdmi_exfil.prng import PRNG
from hdmi_exfil.protocols.base import EncodingProtocol, FrameResult
from hdmi_exfil.protocols.xor_ops import xor_into

# ---------------------------------------------------------------------------
# Fountain-specific constants (protocol-level, not in config.py)
# ---------------------------------------------------------------------------

FOUNT_HEADER_FMT: str = ">HIH"  # magic(2) + seed(4) + K(2)
FOUNT_HEADER_PRE_CRC: int = struct.calcsize(FOUNT_HEADER_FMT)  # 8
FOUNT_CRC_SIZE: int = 4
FOUNT_HEADER_SIZE: int = FOUNT_HEADER_PRE_CRC + FOUNT_CRC_SIZE  # 12

# 3bpp: 3 bits per block (RGB binary), same as sequential protocol
FOUNTAIN_BYTES_PER_FRAME: int = (config.ROWS * config.COLS * 3) // 8  # 12150
PAYLOAD_SIZE: int = FOUNTAIN_BYTES_PER_FRAME - FOUNT_HEADER_SIZE  # 12138


# ---------------------------------------------------------------------------
# FountainDecoder -- belief-propagation peeling decoder
# ---------------------------------------------------------------------------

class FountainDecoder:
    """Incremental LT-code decoder using on-the-fly peeling.

    Accepts fountain droplets (seed + XOR'd payload), reconstructs the
    original *K* chunks via belief propagation.  Functionally identical to
    the decoder formerly in ``receiver_fountain.py`` lines 38-131.
    """

    def __init__(self, total_chunks: int, payload_size: int) -> None:
        self.K: int = total_chunks
        self.payload_size: int = payload_size
        self.chunks: dict[int, np.ndarray] = {}
        self.droplets: list[list] = []
        self.chunk_to_droplets: dict[int, list] = {
            i: [] for i in range(self.K)
        }

    # -- public API ----------------------------------------------------------

    def add_droplet(self, seed: int, data: bytes | bytearray) -> None:
        """Ingest one fountain droplet identified by *seed*."""
        prng = PRNG(seed)

        # Degree distribution (must match JS exactly)
        degree = 1
        r = prng.next_float()
        if r < 0.1:
            degree = 1
        elif r < 0.6:
            degree = 2
        else:
            degree = int(prng.next_float() * min(self.K, 20)) + 1

        # Cap degree to K to prevent infinite loop when degree > K
        degree = min(degree, self.K)

        indices: set[int] = set()
        while len(indices) < degree:
            idx = prng.next() % self.K
            indices.add(idx)

        # On-the-fly peeling: XOR out already-known chunks
        new_indices: set[int] = set()
        current_data = np.frombuffer(data, dtype=np.uint8).copy()

        for idx in indices:
            if idx in self.chunks:
                xor_into(current_data, self.chunks[idx])
            else:
                new_indices.add(idx)

        if not new_indices:
            return  # Redundant droplet -- all chunks already known

        if len(new_indices) == 1:
            found_idx = new_indices.pop()
            self.resolve_chunk(found_idx, current_data)
        else:
            droplet_entry: list = [new_indices, current_data]
            self.droplets.append(droplet_entry)
            for idx in new_indices:
                self.chunk_to_droplets[idx].append(droplet_entry)

    def resolve_chunk(self, chunk_idx: int, chunk_data: np.ndarray) -> None:
        """Record a recovered chunk and propagate via peeling."""
        if chunk_idx in self.chunks:
            return

        self.chunks[chunk_idx] = chunk_data

        affected_droplets = self.chunk_to_droplets[chunk_idx]
        for droplet in affected_droplets:
            indices, data = droplet
            if chunk_idx in indices:
                indices.remove(chunk_idx)
                xor_into(data, chunk_data)
                if len(indices) == 1:
                    next_idx = indices.pop()
                    self.resolve_chunk(next_idx, data)

    def is_complete(self) -> bool:
        """Return ``True`` when all *K* chunks have been recovered."""
        return len(self.chunks) == self.K

    def get_file_data(self) -> bytearray:
        """Concatenate recovered chunks in order, zero-filling gaps."""
        out = bytearray()
        for i in range(self.K):
            if i in self.chunks:
                out.extend(self.chunks[i].tobytes())
            else:
                out.extend(b"\x00" * self.payload_size)
        return out


# ---------------------------------------------------------------------------
# FountainProtocol -- EncodingProtocol implementation
# ---------------------------------------------------------------------------

class FountainProtocol(EncodingProtocol):
    """3-bit-per-block fountain (LT-code) encoding protocol.

    Each frame carries a single fountain droplet:
      - Header: magic(2) + seed(4) + K(2) + crc32(4) = 12 bytes
      - Payload: 12138 bytes of XOR'd chunk data
      - Total: 12150 bytes packed as 97200 bits (3 bits per block, RGB)
    """

    def __init__(self) -> None:
        self._payload_size: int = PAYLOAD_SIZE
        self._bytes_per_frame: int = FOUNTAIN_BYTES_PER_FRAME

    # -- ABC properties ------------------------------------------------------

    @property
    def name(self) -> str:
        return "fountain"

    @property
    def bytes_per_frame(self) -> int:
        return self._payload_size

    # -- encode --------------------------------------------------------------

    def encode_frame(
        self,
        data: bytes,
        frame_index: int,
        total_frames: int,
        **kwargs: object,
    ) -> np.ndarray:
        """Encode *data* into a 3-bit-per-block fountain frame.

        Uses the same RGB binary encoding as SequentialProtocol: each block
        carries 3 bits (one per R/G/B channel, 0 or 255).

        Parameters
        ----------
        data:
            Payload bytes (up to ``PAYLOAD_SIZE``).
        frame_index:
            Logical frame index (used as seed fallback).
        total_frames:
            Total chunk count *K* written into the header.
        seed:
            Explicit seed for the droplet (keyword-only). Defaults to
            *frame_index* when not supplied.
        """
        seed: int = int(kwargs.get("seed", frame_index))

        # Build pre-CRC header: magic(2) + seed(4) + K(2)
        header_pre_crc = struct.pack(
            FOUNT_HEADER_FMT, config.FOUNTAIN_MAGIC, seed, total_frames,
        )

        # CRC32 over pre-CRC header + payload
        crc = zlib.crc32(header_pre_crc + data) & 0xFFFFFFFF
        crc_bytes = struct.pack(">I", crc)

        # Full frame bytes: header_pre_crc(8) + crc(4) + payload
        frame_bytes = header_pre_crc + crc_bytes + data

        # Pad to exactly FOUNTAIN_BYTES_PER_FRAME if payload is short
        if len(frame_bytes) < self._bytes_per_frame:
            frame_bytes += b"\x00" * (self._bytes_per_frame - len(frame_bytes))

        # Convert bytes -> bits, 3 bits per block (RGB binary)
        byte_arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        bits = np.unpackbits(byte_arr)

        total_bits_needed = config.BLOCKS_PER_FRAME * 3
        if len(bits) < total_bits_needed:
            bits = np.pad(bits, (0, total_bits_needed - len(bits)), "constant")

        # Reshape to (BLOCKS_PER_FRAME, 3) -> RGB values per block
        pixel_bits = bits[:total_bits_needed].reshape(
            (config.BLOCKS_PER_FRAME, 3),
        )
        pixel_values = pixel_bits * 255

        # Reshape to (ROWS, COLS, 3) grid
        blocks_grid = pixel_values.reshape(
            (config.ROWS, config.COLS, 3),
        ).astype(np.uint8)

        # Scale up to full resolution via nearest-neighbour interpolation
        import cv2  # noqa: C0415  (lazy import -- not needed at module level)

        frame_img: np.ndarray = cv2.resize(
            blocks_grid,
            (config.WIDTH, config.HEIGHT),
            interpolation=cv2.INTER_NEAREST,
        )
        return frame_img

    # -- decode --------------------------------------------------------------

    def decode_frame(self, sampled_grid: np.ndarray) -> FrameResult:
        """Decode a sampled block grid into a ``FrameResult``.

        Uses 3bpp decoding (threshold all 3 RGB channels):
          1. Flatten grid, threshold all channels > 128 to get 3 bits/block
          2. Pack bits to bytes
          3. Parse fountain header (magic + seed + K + CRC)
          4. Verify CRC32
        """
        # Flatten and threshold all 3 channels: > 128 => bit=1 (3bpp)
        flat = sampled_grid.reshape(-1, 3)
        bits = (flat > 128).astype(np.uint8)
        flat_bits = bits.reshape(-1)
        raw_bytes = np.packbits(flat_bits).tobytes()

        # Need at least a full header
        if len(raw_bytes) < FOUNT_HEADER_SIZE:
            return FrameResult(
                data=None, frame_type=None, frame_index=None,
                total_frames=None, is_valid=False,
            )

        try:
            # Parse pre-CRC fields
            magic, seed, K = struct.unpack(
                FOUNT_HEADER_FMT, raw_bytes[:FOUNT_HEADER_PRE_CRC],
            )

            if magic != config.FOUNTAIN_MAGIC:
                return FrameResult(
                    data=None, frame_type=None, frame_index=None,
                    total_frames=None, is_valid=False,
                )

            # Extract stored CRC
            stored_crc = struct.unpack(
                ">I", raw_bytes[FOUNT_HEADER_PRE_CRC:FOUNT_HEADER_SIZE],
            )[0]

            payload = raw_bytes[FOUNT_HEADER_SIZE:]

            # Verify CRC32 over pre-CRC header + payload
            computed_crc = (
                zlib.crc32(raw_bytes[:FOUNT_HEADER_PRE_CRC] + payload)
                & 0xFFFFFFFF
            )
            if computed_crc != stored_crc:
                return FrameResult(
                    data=None, frame_type=None, frame_index=None,
                    total_frames=None, is_valid=False,
                )

            return FrameResult(
                data=payload,
                frame_type=None,
                frame_index=seed,
                total_frames=K,
                is_valid=True,
            )

        except Exception:
            return FrameResult(
                data=None, frame_type=None, frame_index=None,
                total_frames=None, is_valid=False,
            )
