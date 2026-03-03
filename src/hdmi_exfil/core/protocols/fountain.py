"""Fountain-code (LT-code) encoding protocol implementation.

Implements FountainProtocol (3-bit-per-block RGB binary encoding with LT-code
redundancy) and FountainDecoder (hybrid BP + GE decoder) behind the
``EncodingProtocol`` ABC defined in ``base.py``.

Each block encodes 3 bits (one per R/G/B channel, each either 0 or 255),
matching the same 3bpp pattern used by SequentialProtocol.  This gives
12,150 bytes per frame (12,138 payload) -- a 3x capacity increase over the
original 1bpp (4,050 bytes / 4,038 payload) encoding.

Migrated from the monolithic ``receiver_fountain.py`` -- all logic is
functionally identical, but now uses the shared ``hdmi_exfil.core.prng.PRNG``
class and the canonical ``hdmi_exfil.core.config`` constants.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

from hdmi_exfil.core import config
from hdmi_exfil.core.config import DEFAULT_PROFILE, ResolutionProfile
from hdmi_exfil.core.prng import PRNG
from hdmi_exfil.core.protocols.base import EncodingProtocol, FrameResult
from hdmi_exfil.core.protocols.degree import robust_soliton_cdf, sample_degree
from hdmi_exfil.core.protocols.xor_ops import xor_into

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
# FountainDecoder -- hybrid BP + Gaussian elimination decoder
# ---------------------------------------------------------------------------

class FountainDecoder:
    """Incremental LT-code decoder using hybrid BP + GE.

    Primary decoding path is belief-propagation (peeling).  When BP stalls
    (no degree-1 droplets remain), Gaussian elimination in GF(2) is
    attempted on the unresolved droplet system to recover remaining chunks.

    Accepts fountain droplets (seed + XOR'd payload), reconstructs the
    original *K* chunks.
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

        # Robust Soliton Distribution for degree selection
        cdf = robust_soliton_cdf(self.K)
        degree = sample_degree(cdf, prng)

        # Safety cap: degree cannot exceed K
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

        # Auto-trigger GE when BP stalls and enough equations exist
        if not self.is_complete():
            self.try_gaussian_elimination()

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

    # -- Gaussian elimination fallback ---------------------------------------

    def try_gaussian_elimination(self) -> None:
        """Attempt GE if enough unresolved equations exist.

        Lightweight check: only invokes the full GE solver when the
        number of unresolved droplets is at least as large as the number
        of unknown chunks (necessary condition for solvability).
        """
        if self.is_complete():
            return

        n_unknown = self.K - len(self.chunks)
        n_unresolved = sum(1 for d in self.droplets if len(d[0]) > 0)

        if n_unresolved >= n_unknown:
            self.gaussian_elimination_fallback()

    def gaussian_elimination_fallback(self) -> bool:
        """Solve unresolved droplets via GF(2) Gaussian elimination.

        Collects all droplets with remaining unknown indices, builds a
        binary coefficient matrix and data matrix, row-reduces in GF(2),
        and back-substitutes to recover unknown chunks.

        Returns ``True`` if any new chunks were resolved, ``False``
        otherwise (e.g. underdetermined system or no unresolved work).
        """
        # 1. Collect unresolved droplets
        unresolved = [
            (d[0].copy(), d[1].copy())
            for d in self.droplets
            if len(d[0]) > 0
        ]
        if not unresolved:
            return False

        # 2. Identify unknown chunk indices
        unknown_set: set[int] = set()
        for indices, _ in unresolved:
            unknown_set.update(indices)

        # Remove any chunk indices that are already known
        unknown_set -= set(self.chunks.keys())
        if not unknown_set:
            return False

        unknown_list = sorted(unknown_set)
        col_map = {chunk_idx: col for col, chunk_idx in enumerate(unknown_list)}
        n_unknowns = len(unknown_list)
        n_equations = len(unresolved)

        # 3. Underdetermined check
        if n_equations < n_unknowns:
            return False

        # 4. Build binary matrix M (n_equations x n_unknowns) in GF(2)
        #    and data matrix D (n_equations x payload_size)
        M = np.zeros((n_equations, n_unknowns), dtype=np.uint8)
        D = np.zeros((n_equations, self.payload_size), dtype=np.uint8)

        for row, (indices, data) in enumerate(unresolved):
            # XOR out any known chunks from this droplet's data
            row_data = data.copy()
            for idx in list(indices):
                if idx in self.chunks:
                    row_data ^= self.chunks[idx]
                elif idx in col_map:
                    M[row, col_map[idx]] = 1
            D[row] = row_data

        # 5. Forward elimination (row echelon form in GF(2))
        pivot_row = 0
        pivot_cols: list[int] = []  # tracks which column each pivot row solves

        for col in range(n_unknowns):
            # Find pivot: first row at or below pivot_row with M[row][col] == 1
            found = -1
            for row in range(pivot_row, n_equations):
                if M[row, col] == 1:
                    found = row
                    break

            if found == -1:
                continue  # No pivot in this column; skip

            # Swap pivot row into position
            if found != pivot_row:
                M[[pivot_row, found]] = M[[found, pivot_row]]
                D[[pivot_row, found]] = D[[found, pivot_row]]

            # Eliminate all other rows with a 1 in this column
            for row in range(n_equations):
                if row != pivot_row and M[row, col] == 1:
                    M[row] ^= M[pivot_row]  # GF(2) XOR
                    D[row] ^= D[pivot_row]  # GF(2) XOR

            pivot_cols.append(col)
            pivot_row += 1

        # 6. Back-substitution: extract solved chunks
        #    After full elimination (forward + back in one pass above),
        #    each pivot row has exactly one 1 in its pivot column.
        resolved_any = False
        for p_row, col in enumerate(pivot_cols):
            # Verify this row has a clean pivot (M[p_row][col] == 1)
            if M[p_row, col] != 1:
                continue

            # Check that no other unknowns remain in this row
            row_sum = int(np.sum(M[p_row]))
            if row_sum != 1:
                continue  # Row has other unknowns; cannot solve

            chunk_idx = unknown_list[col]
            if chunk_idx not in self.chunks:
                self.resolve_chunk(chunk_idx, D[p_row].copy())
                resolved_any = True

        return resolved_any


# ---------------------------------------------------------------------------
# FountainProtocol -- EncodingProtocol implementation
# ---------------------------------------------------------------------------

class FountainProtocol(EncodingProtocol):
    """3-bit-per-block fountain (LT-code) encoding protocol.

    Each frame carries a single fountain droplet:
      - Header: magic(2) + seed(4) + K(2) + crc32(4) = 12 bytes
      - Payload: XOR'd chunk data (size depends on profile)
      - Total: packed as bits (3 bits per block, RGB)

    Parameters
    ----------
    profile:
        Optional ``ResolutionProfile`` controlling spatial dimensions and
        capacity.  Defaults to ``DEFAULT_PROFILE`` (1080p/240fps) for full
        backward compatibility.
    """

    def __init__(self, profile: ResolutionProfile | None = None) -> None:
        self._profile = profile or DEFAULT_PROFILE
        # Recompute payload sizes from profile
        self._total_bytes: int = self._profile.bits_per_frame // 8
        self._payload_size: int = self._total_bytes - FOUNT_HEADER_SIZE

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

        # Pad to exactly total_bytes if payload is short
        if len(frame_bytes) < self._total_bytes:
            frame_bytes += b"\x00" * (self._total_bytes - len(frame_bytes))

        # Convert bytes -> bits, 3 bits per block (RGB binary)
        byte_arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        bits = np.unpackbits(byte_arr)

        total_bits_needed = self._profile.blocks_per_frame * 3
        if len(bits) < total_bits_needed:
            bits = np.pad(bits, (0, total_bits_needed - len(bits)), "constant")

        # Reshape to (blocks_per_frame, 3) -> RGB values per block
        pixel_bits = bits[:total_bits_needed].reshape(
            (self._profile.blocks_per_frame, 3),
        )
        pixel_values = pixel_bits * 255

        # Reshape to (rows, cols, 3) grid
        blocks_grid = pixel_values.reshape(
            (self._profile.rows, self._profile.cols, 3),
        ).astype(np.uint8)

        # Scale up to full resolution via nearest-neighbour (np.repeat)
        frame_img = np.repeat(
            np.repeat(blocks_grid, self._profile.block_size, axis=0),
            self._profile.block_size,
            axis=1,
        )
        # Safety trim to exact profile dimensions
        frame_img = frame_img[: self._profile.height, : self._profile.width, :]
        # Flip RGB→BGR for OpenCV/pygame display (they expect BGR channel order)
        return frame_img[..., ::-1]

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
        # OpenCV captures in BGR order; flip to RGB to match the sender's
        # bit packing (R channel = first bit, G = second, B = third).
        flat = sampled_grid[..., ::-1].reshape(-1, 3)
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
