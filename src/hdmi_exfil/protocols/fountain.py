"""Fountain-code (LT-code) encoding protocol implementation.

Implements FountainProtocol (1-bit-per-block encoding with LT-code redundancy)
and FountainDecoder (belief-propagation / peeling decoder) behind the
``EncodingProtocol`` ABC defined in ``base.py``.

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

# ---------------------------------------------------------------------------
# Fountain-specific constants (protocol-level, not in config.py)
# ---------------------------------------------------------------------------

FOUNT_HEADER_FMT: str = ">HIH"  # magic(2) + seed(4) + K(2)
FOUNT_HEADER_PRE_CRC: int = struct.calcsize(FOUNT_HEADER_FMT)  # 8
FOUNT_CRC_SIZE: int = 4
FOUNT_HEADER_SIZE: int = FOUNT_HEADER_PRE_CRC + FOUNT_CRC_SIZE  # 12

# Fountain mode: 1 bit per block (black/white), NOT 3 bits like sequential
FOUNTAIN_BYTES_PER_FRAME: int = (config.ROWS * config.COLS) // 8  # 4050
PAYLOAD_SIZE: int = FOUNTAIN_BYTES_PER_FRAME - FOUNT_HEADER_SIZE  # 4038


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
        self.chunks: dict[int, bytearray] = {}
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
        current_data = bytearray(data)

        for idx in indices:
            if idx in self.chunks:
                chunk_data = self.chunks[idx]
                for i in range(len(current_data)):
                    current_data[i] ^= chunk_data[i]
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

    def resolve_chunk(self, chunk_idx: int, chunk_data: bytearray) -> None:
        """Record a recovered chunk and propagate via peeling."""
        if chunk_idx in self.chunks:
            return

        self.chunks[chunk_idx] = chunk_data

        affected_droplets = self.chunk_to_droplets[chunk_idx]
        for droplet in affected_droplets:
            indices, data = droplet
            if chunk_idx in indices:
                indices.remove(chunk_idx)
                for i in range(len(data)):
                    data[i] ^= chunk_data[i]
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
                out.extend(self.chunks[i])
            else:
                out.extend(b"\x00" * self.payload_size)
        return out


# ---------------------------------------------------------------------------
# FountainProtocol -- EncodingProtocol implementation
# ---------------------------------------------------------------------------

class FountainProtocol(EncodingProtocol):
    """1-bit-per-block fountain (LT-code) encoding protocol.

    Each frame carries a single fountain droplet:
      - Header: magic(2) + seed(4) + K(2) + crc32(4) = 12 bytes
      - Payload: 4038 bytes of XOR'd chunk data
      - Total: 4050 bytes packed as 32400 bits (1 bit per block)
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
        """Encode *data* into a 1-bit-per-block fountain frame.

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

        # Convert bytes -> bits (1 bit per block)
        byte_arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        bits = np.unpackbits(byte_arr)

        total_blocks = config.ROWS * config.COLS
        bits = bits[:total_blocks]  # Trim to exact block count

        # Map bits to RGB: 1 -> white (255,255,255), 0 -> black (0,0,0)
        rgb = np.zeros((total_blocks, 3), dtype=np.uint8)
        rgb[bits == 1] = 255

        # Reshape to (ROWS, COLS, 3) grid
        blocks_grid = rgb.reshape((config.ROWS, config.COLS, 3))

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

        Mirrors the decode path from ``receiver_fountain.py``:
          1. Flatten grid, threshold green channel > 128 to get bits
          2. Pack bits to bytes
          3. Parse fountain header (magic + seed + K + CRC)
          4. Verify CRC32
        """
        # Flatten and threshold: green channel > 128 => bit=1
        flat = sampled_grid.reshape(-1, 3)
        bits = (flat[:, 1] > 128).astype(np.uint8)
        raw_bytes = np.packbits(bits).tobytes()

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
