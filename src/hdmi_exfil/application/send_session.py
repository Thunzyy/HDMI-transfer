"""Shared send session used by the CLI and future web sender adapters."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from hdmi_exfil.application.events import FramePacket
from hdmi_exfil.core.config import DEFAULT_PROFILE, PROFILES, ResolutionProfile
from hdmi_exfil.core.file_handling.metadata import build_start_metadata
from hdmi_exfil.core.file_handling.reader import read_input
from hdmi_exfil.core.prng import choose_indices
from hdmi_exfil.core.protocols import get_protocol
from hdmi_exfil.core.protocols.base import EncodingProtocol
from hdmi_exfil.core.protocols.xor_ops import xor_into


@dataclass(frozen=True)
class SendSession:
    """Pure send workflow state detached from CLI rendering concerns."""

    mode: str
    profile: ResolutionProfile
    protocol: EncodingProtocol
    filename: str
    file_data: bytes
    total_frames: int
    metadata: bytes | None = None
    chunks: tuple[np.ndarray, ...] = ()
    max_droplets: int | None = None

    @classmethod
    def from_input(
        cls,
        *,
        input_path: str,
        mode: str = "sequential",
        profile: ResolutionProfile | None = None,
        profile_name: str | None = None,
        fountain_redundancy: float | None = None,
    ) -> SendSession:
        """Build a send session from a file or directory input path."""
        resolved_profile = cls._resolve_profile(
            profile=profile,
            profile_name=profile_name,
        )
        filename, file_data = read_input(input_path)
        protocol = get_protocol(mode, profile=resolved_profile)

        if mode == "sequential":
            total_frames = math.ceil(
                len(file_data) / resolved_profile.seq_bytes_per_frame
            )
            return cls(
                mode=mode,
                profile=resolved_profile,
                protocol=protocol,
                filename=filename,
                file_data=file_data,
                total_frames=total_frames,
            )

        if mode != "fountain":
            raise ValueError(f"Unsupported send mode: {mode}")

        metadata = build_start_metadata(filename, file_data)
        wrapped = metadata + file_data
        payload_size = resolved_profile.fount_bytes_per_frame
        total_frames = math.ceil(len(wrapped) / payload_size)
        chunks = cls._chunk_fountain_payload(wrapped, payload_size)

        max_droplets: int | None = None
        if fountain_redundancy is not None:
            max_droplets = math.ceil(total_frames * fountain_redundancy)

        return cls(
            mode=mode,
            profile=resolved_profile,
            protocol=protocol,
            filename=filename,
            file_data=file_data,
            total_frames=total_frames,
            metadata=metadata,
            chunks=chunks,
            max_droplets=max_droplets,
        )

    @property
    def file_size(self) -> int:
        return len(self.file_data)

    @property
    def sha256_hex(self) -> str:
        return hashlib.sha256(self.file_data).hexdigest()

    @property
    def bytes_per_frame(self) -> int:
        if self.mode == "sequential":
            return self.profile.seq_bytes_per_frame
        return self.profile.fount_bytes_per_frame

    def iter_frame_packets(self) -> Iterator[FramePacket]:
        """Yield encoded frames in transmission order for the current mode."""
        if self.mode == "sequential":
            yield from self._iter_sequential_packets()
            return
        yield from self._iter_fountain_packets()

    @staticmethod
    def advance_seed(seed: int) -> int:
        """Advance a fountain seed with the protocol's wraparound rules."""
        seed = (seed + 1) & 0xFFFFFFFF
        if seed == 0:
            return 1
        return seed

    @staticmethod
    def _resolve_profile(
        *,
        profile: ResolutionProfile | None,
        profile_name: str | None,
    ) -> ResolutionProfile:
        if profile is not None:
            return profile
        if profile_name is not None:
            return PROFILES[profile_name]
        return DEFAULT_PROFILE

    @staticmethod
    def _chunk_fountain_payload(
        wrapped_payload: bytes,
        payload_size: int,
    ) -> tuple[np.ndarray, ...]:
        chunks: list[np.ndarray] = []
        total_chunks = math.ceil(len(wrapped_payload) / payload_size)

        for chunk_index in range(total_chunks):
            start = chunk_index * payload_size
            end = min(start + payload_size, len(wrapped_payload))
            chunk = np.zeros(payload_size, dtype=np.uint8)
            chunk[: end - start] = np.frombuffer(
                wrapped_payload[start:end],
                dtype=np.uint8,
            )
            chunks.append(chunk)

        return tuple(chunks)

    def _iter_sequential_packets(self) -> Iterator[FramePacket]:
        protocol = self.protocol
        start_frame = protocol.encode_start_frame(
            self.filename,
            self.file_data,
            self.total_frames,
        )
        yield FramePacket(
            kind="start",
            frame=start_frame,
            frame_index=0,
            total_frames=self.total_frames,
        )

        for frame_index in range(self.total_frames):
            start = frame_index * self.profile.seq_bytes_per_frame
            end = min(start + self.profile.seq_bytes_per_frame, len(self.file_data))
            payload = self.file_data[start:end]
            frame = protocol.encode_frame(payload, frame_index, self.total_frames)
            yield FramePacket(
                kind="data",
                frame=frame,
                frame_index=frame_index,
                total_frames=self.total_frames,
            )

        end_frame = protocol.encode_end_frame(self.total_frames)
        yield FramePacket(
            kind="end",
            frame=end_frame,
            frame_index=self.total_frames,
            total_frames=self.total_frames,
        )

    def _iter_fountain_packets(self) -> Iterator[FramePacket]:
        seed = 1
        frame_index = 0
        expected_droplets = self.max_droplets or 0
        payload_size = self.profile.fount_bytes_per_frame

        while self.max_droplets is None or frame_index < self.max_droplets:
            indices = choose_indices(seed, self.total_frames)
            payload = np.zeros(payload_size, dtype=np.uint8)

            for chunk_index in indices:
                xor_into(payload, self.chunks[chunk_index])

            frame = self.protocol.encode_frame(
                payload.tobytes(),
                frame_index,
                self.total_frames,
                seed=seed,
                expected_droplets=expected_droplets,
            )
            yield FramePacket(
                kind="droplet",
                frame=frame,
                frame_index=frame_index,
                total_frames=self.total_frames,
                seed=seed,
            )

            frame_index += 1
            seed = self.advance_seed(seed)
