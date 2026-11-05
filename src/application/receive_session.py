"""Shared receive session used by CLI and web receiver adapters."""

from __future__ import annotations

import math
import time

import numpy as np

from hdmi_transfer.application.events import ReceiveEvent
from hdmi_transfer.application.preflight import is_preflight_start_result
from hdmi_transfer.core.config import (
    DEFAULT_PROFILE,
    FRAME_TYPE_DATA,
    FRAME_TYPE_END,
    FRAME_TYPE_START,
    PROFILES,
    ResolutionProfile,
)
from hdmi_transfer.core.file_handling.metadata import (
    parse_fountain_metadata,
    parse_start_metadata,
)
from hdmi_transfer.core.file_handling.writer import verify_integrity
from hdmi_transfer.core.protocols import get_protocol
from hdmi_transfer.core.protocols.base import EncodingProtocol, FrameResult
from hdmi_transfer.core.protocols.fountain import FountainDecoder


class ReceiveSession:
    """Protocol-aware receive state machine independent from capture/UI code."""

    def __init__(
        self,
        *,
        mode: str = "auto",
        profile: ResolutionProfile | None = None,
        profile_name: str | None = None,
        progress_interval_s: float = 0.0,
    ) -> None:
        if not math.isfinite(progress_interval_s) or progress_interval_s < 0:
            raise ValueError("progress_interval_s must be finite and nonnegative")
        self._progress_interval_s = progress_interval_s
        self._last_progress_at: float | None = None
        self.mode = mode
        self.profile = self._resolve_profile(
            profile=profile,
            profile_name=profile_name,
        )
        self._sequential_protocol = get_protocol("sequential", profile=self.profile)
        self._fountain_protocol = get_protocol("fountain", profile=self.profile)
        self.detected_protocol: str | None = (
            mode if mode in {"sequential", "fountain"} else None
        )
        self._started_at: float | None = None
        self._completed = False
        self._reset_sequential_state()
        self._reset_fountain_state()

    @property
    def sequential_protocol(self) -> EncodingProtocol:
        return self._sequential_protocol

    @property
    def fountain_protocol(self) -> EncodingProtocol:
        return self._fountain_protocol

    @property
    def has_progress(self) -> bool:
        """Whether any transfer metadata or data has been accepted."""
        return bool(
            self._fountain_decoder is not None
            or self._seq_saw_start
            or self._seq_saw_end
            or self._seq_received
        )

    def _elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    def _progress_due(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if (
            not force
            and self._last_progress_at is not None
            and now - self._last_progress_at < self._progress_interval_s
        ):
            return False
        self._last_progress_at = now
        return True

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

    def feed_sampled_grid(self, sampled_grid: np.ndarray) -> list[ReceiveEvent]:
        """Decode a sampled frame and emit zero or more session events."""
        if self._completed:
            return []

        if self.detected_protocol == "sequential" or self.mode == "sequential":
            return self.feed_frame_result(
                "sequential",
                self._sequential_protocol.decode_frame(sampled_grid),
            )

        if self.detected_protocol == "fountain" or self.mode == "fountain":
            return self.feed_frame_result(
                "fountain",
                self._fountain_protocol.decode_frame(sampled_grid),
            )

        sequential_result = self._sequential_protocol.decode_frame(sampled_grid)
        if sequential_result.is_valid:
            return self.feed_frame_result("sequential", sequential_result)

        fountain_result = self._fountain_protocol.decode_frame(sampled_grid)
        if fountain_result.is_valid:
            return self.feed_frame_result("fountain", fountain_result)

        return []

    def feed_frame_result(
        self,
        protocol: str,
        result: FrameResult,
    ) -> list[ReceiveEvent]:
        """Consume a decoded frame result from an external adapter."""
        if self._completed or not result.is_valid:
            return []

        # Calibration uses a sequential START frame even before a Fountain
        # transfer. It must neither select a protocol nor start a file.
        if protocol == "sequential" and is_preflight_start_result(result):
            return []

        if self.mode in {"sequential", "fountain"} and protocol != self.mode:
            return []

        events: list[ReceiveEvent] = []
        if self._started_at is None:
            self._started_at = time.monotonic()

        if self.detected_protocol is None:
            self.detected_protocol = protocol
            events.append(ReceiveEvent(
                kind="status",
                data={
                    "state": "detected",
                    "message": f"Detected {protocol} protocol.",
                    "protocol": protocol,
                },
            ))
        elif protocol != self.detected_protocol:
            return []

        if protocol == "sequential":
            events.extend(self._handle_sequential_result(result))
            return events

        if protocol == "fountain":
            events.extend(self._handle_fountain_result(result))
            return events

        raise ValueError(f"Unsupported receive protocol: {protocol}")

    def finalize_partial(self) -> ReceiveEvent | None:
        """Finalize a recoverable partial transfer when the adapter stops early."""
        if self._completed:
            return None

        if (
            self.detected_protocol == "sequential"
            and self._seq_received
            and self._seq_total_expected is not None
        ):
            return self._build_sequential_complete_event()

        return None

    def _reset_sequential_state(self) -> None:
        self._seq_received: dict[int, bytes] = {}
        self._seq_expected_sha256: bytes | None = None
        self._seq_expected_size: int | None = None
        self._seq_expected_name: str | None = None
        self._seq_total_expected: int | None = None
        self._seq_last_data_idx: int | None = None
        self._seq_pass_count = 0
        self._seq_saw_start = False
        self._seq_saw_end = False
        self._seq_waiting_for_metadata_reported = False
        self._seq_bytes_received = 0

    def _handle_sequential_result(self, result: FrameResult) -> list[ReceiveEvent]:
        events: list[ReceiveEvent] = []
        ftype = result.frame_type
        data = result.data
        frame_index = result.frame_index
        total_frames = result.total_frames

        if ftype == FRAME_TYPE_START:
            self._seq_saw_start = True
            if self._seq_total_expected is None and total_frames:
                self._seq_total_expected = total_frames
            if data is not None and self._seq_expected_name is None:
                file_size, sha256_hash, filename = parse_start_metadata(data)
                if file_size is not None:
                    self._seq_expected_size = file_size
                    self._seq_expected_sha256 = sha256_hash
                    self._seq_expected_name = filename
            if self._seq_expected_name is not None and self._seq_total_expected:
                self._seq_waiting_for_metadata_reported = False
                events.append(ReceiveEvent(
                    kind="status",
                    data={
                        "state": "receiving",
                        "message": (
                            f"File: {self._seq_expected_name} "
                            f"({self._seq_expected_size} bytes, "
                            f"{self._seq_total_expected} frames)"
                        ),
                        "protocol": "sequential",
                        "total_chunks": self._seq_total_expected,
                        "start_seen": True,
                        "end_seen": self._seq_saw_end,
                        "pass_count": self._seq_pass_count,
                    },
                ))
            if (
                self._seq_total_expected
                and len(self._seq_received) >= self._seq_total_expected
            ):
                events.append(self._build_sequential_complete_event())
            return events

        if ftype == FRAME_TYPE_DATA and data is not None and frame_index is not None:
            if self._seq_total_expected is None and total_frames:
                self._seq_total_expected = total_frames
            if (
                self._seq_total_expected
                and self._seq_expected_name is None
                and not self._seq_waiting_for_metadata_reported
            ):
                self._seq_waiting_for_metadata_reported = True
                events.append(ReceiveEvent(
                    kind="status",
                    data={
                        "state": "receiving",
                        "message": (
                            "Sequential data detected "
                            f"({self._seq_total_expected} frames). "
                            "Waiting for START metadata..."
                        ),
                        "protocol": "sequential",
                        "total_chunks": self._seq_total_expected,
                        "start_seen": self._seq_saw_start,
                        "end_seen": self._seq_saw_end,
                        "pass_count": self._seq_pass_count,
                    },
                ))
            if (
                self._seq_total_expected
                and len(self._seq_received) >= self._seq_total_expected
                and self._seq_last_data_idx is not None
                and frame_index < self._seq_last_data_idx
            ):
                self._seq_pass_count += 1
                events.append(self._build_sequential_complete_event())
                return events
            if frame_index not in self._seq_received:
                self._seq_received[frame_index] = data
                self._seq_bytes_received += len(data)
            self._seq_last_data_idx = frame_index
            if self._seq_total_expected and self._progress_due():
                duration = self._elapsed()
                percent = round(
                    len(self._seq_received) / self._seq_total_expected * 100,
                    1,
                )
                if percent >= 100.0:
                    percent = 99.9
                events.append(ReceiveEvent(
                    kind="progress",
                    data={
                        "protocol": "sequential",
                        "chunks_decoded": len(self._seq_received),
                        "total_chunks": self._seq_total_expected,
                        "percent": percent,
                        "bytes_received": self._seq_bytes_received,
                        "speed_kbps": round(
                            self._seq_bytes_received / duration / 1024,
                            1,
                        ) if duration > 2 else 0,
                        "eta_seconds": -1,
                        "decoded_indices": sorted(self._seq_received.keys()),
                        "start_seen": self._seq_saw_start,
                        "end_seen": self._seq_saw_end,
                        "pass_count": self._seq_pass_count,
                    },
                ))
            return events

        if ftype == FRAME_TYPE_END:
            self._seq_saw_end = True
            if (
                self._seq_total_expected
                and len(self._seq_received) >= self._seq_total_expected
            ):
                events.append(self._build_sequential_complete_event())
            return events

        return events

    def _build_sequential_complete_event(self) -> ReceiveEvent:
        full_data, missing = self._reassemble_sequential_data()
        if self._seq_expected_size is not None:
            file_content = full_data[: self._seq_expected_size]
        else:
            file_content = full_data

        duration = self._elapsed()
        speed_mbps = (
            (len(file_content) * 8) / duration / 1_000_000
            if duration > 0
            else 0
        )
        sha256_ok = bool(
            self._seq_expected_sha256
            and verify_integrity(file_content, self._seq_expected_sha256),
        )
        filename = self._seq_expected_name or f"received_{int(time.time())}.bin"

        self._completed = True
        return ReceiveEvent(
            kind="complete",
            data={
                "protocol": "sequential",
                "filename": filename,
                "size": len(file_content),
                "sha256_ok": sha256_ok,
                "sha256_available": self._seq_expected_sha256 is not None,
                "duration_s": round(duration, 2),
                "speed_mbps": round(speed_mbps, 2),
                "bytes_received": self._seq_bytes_received,
                "chunks_decoded": len(self._seq_received),
                "total_chunks": self._seq_total_expected,
                "start_seen": self._seq_saw_start,
                "end_seen": self._seq_saw_end,
                "pass_count": self._seq_pass_count,
                "missing_frames": missing,
                "file_content": file_content,
            },
        )

    def _reassemble_sequential_data(self) -> tuple[bytes, list[int]]:
        if self._seq_total_expected is None:
            return b"", []

        bytes_per_frame = self.profile.seq_bytes_per_frame
        full_data = bytearray()
        missing: list[int] = []
        for frame_index in range(self._seq_total_expected):
            chunk = self._seq_received.get(frame_index)
            if chunk is None:
                missing.append(frame_index)
                full_data.extend(b"\x00" * bytes_per_frame)
            else:
                full_data.extend(chunk)
        return bytes(full_data), missing

    def _reset_fountain_state(self) -> None:
        self._fountain_decoder: FountainDecoder | None = None
        self._fountain_bytes_received = 0
        self._fountain_unique_bytes_received = 0
        self._fountain_droplets_received = 0
        self._fountain_unique_droplets_received = 0
        self._fountain_expected_droplets: int | None = None
        self._fountain_seen_seeds: set[int] = set()
        self._fountain_content_range: tuple[int, int] | None = None

    def _handle_fountain_result(self, result: FrameResult) -> list[ReceiveEvent]:
        if (
            not result.data
            or result.frame_index is None
            or result.total_frames is None
        ):
            return []

        total_chunks = result.total_frames
        if total_chunks <= 0 or total_chunks > 60000:
            return []

        payload = result.data
        seed = result.frame_index
        expected_droplets = (
            max(0, int(result.max_frames))
            if result.max_frames is not None
            else None
        )
        events: list[ReceiveEvent] = []

        if self._fountain_decoder is None or self._fountain_decoder.K != total_chunks:
            self._reset_fountain_state()
            self._fountain_decoder = FountainDecoder(total_chunks, len(payload))
            self._fountain_expected_droplets = expected_droplets
            self._last_progress_at = None
            events.append(ReceiveEvent(
                kind="status",
                data={
                    "state": "receiving",
                    "message": f"Transmission detected! K={total_chunks} chunks",
                    "protocol": "fountain",
                    "total_chunks": total_chunks,
                    "expected_droplets": expected_droplets,
                },
            ))
        elif expected_droplets is not None and self._fountain_expected_droplets is None:
            self._fountain_expected_droplets = expected_droplets

        assert self._fountain_decoder is not None
        if len(payload) != self._fountain_decoder.payload_size:
            return events

        self._fountain_bytes_received += len(payload)
        self._fountain_droplets_received += 1
        if seed not in self._fountain_seen_seeds:
            self._fountain_seen_seeds.add(seed)
            self._fountain_unique_droplets_received += 1
            self._fountain_unique_bytes_received += len(payload)
            self._fountain_decoder.add_droplet(seed, payload)

        complete = self._fountain_decoder.is_complete()
        if self._progress_due(force=complete):
            events.append(self._build_fountain_progress_event())
        if complete:
            events.append(self._build_fountain_complete_event())
        return events

    def _fountain_useful_bytes(self, decoded_indices: list[int]) -> int | None:
        """Count recovered file bytes, excluding metadata and final padding.

        A Fountain file's metadata may itself span multiple chunks. Until
        that prefix is recovered, the useful size is unknown, not zero.
        This work runs only at the requested progress cadence.
        """
        decoder = self._fountain_decoder
        assert decoder is not None
        if self._fountain_content_range is None:
            prefix = bytearray()
            # The metadata parser allows at most 1024 filename bytes.
            prefix_chunks = min(decoder.K, math.ceil(1062 / decoder.payload_size))
            for index in range(prefix_chunks):
                chunk = decoder.chunks.get(index)
                if chunk is None:
                    break
                prefix.extend(chunk.tobytes())
                size, _, _, offset = parse_fountain_metadata(prefix)
                if size is not None and offset is not None:
                    if offset + size <= decoder.K * decoder.payload_size:
                        self._fountain_content_range = (offset, offset + size)
                    break
        if self._fountain_content_range is None:
            return None
        start, end = self._fountain_content_range
        return sum(
            max(
                0,
                min(end, (index + 1) * decoder.payload_size)
                - max(start, index * decoder.payload_size),
            )
            for index in decoded_indices
        )

    def _build_fountain_progress_event(self) -> ReceiveEvent:
        assert self._fountain_decoder is not None
        decoded_indices = sorted(self._fountain_decoder.chunks)
        decoded = len(decoded_indices)
        useful_bytes = self._fountain_useful_bytes(decoded_indices)
        duration = self._elapsed()
        speed = (useful_bytes or 0) / duration if duration > 2 else 0
        captured_speed = self._fountain_bytes_received / duration if duration > 2 else 0
        unique_speed = (
            self._fountain_unique_bytes_received / duration if duration > 2 else 0
        )
        percent = round(decoded / self._fountain_decoder.K * 100, 1)
        if percent >= 100.0:
            percent = 99.9
        return ReceiveEvent(
            kind="progress",
            data={
                "protocol": "fountain",
                "chunks_decoded": decoded,
                "total_chunks": self._fountain_decoder.K,
                "percent": percent,
                "droplets_received": self._fountain_droplets_received,
                "unique_droplets_received": (
                    self._fountain_unique_droplets_received
                ),
                "expected_droplets": self._fountain_expected_droplets,
                "bytes_received": self._fountain_bytes_received,
                "captured_bytes": self._fountain_bytes_received,
                "unique_bytes_received": self._fountain_unique_bytes_received,
                "duplicate_droplets_received": (
                    self._fountain_droplets_received
                    - self._fountain_unique_droplets_received
                ),
                "useful_bytes_decoded": useful_bytes,
                "speed_kbps": round(speed / 1024, 1) if speed > 0 else 0,
                "captured_speed_kbps": round(captured_speed / 1024, 1),
                "unique_speed_kbps": round(unique_speed / 1024, 1),
                # Fountain progress can jump when equations resolve; captured
                # bandwidth cannot predict how many useful equations remain.
                "eta_seconds": -1,
                "decoded_indices": decoded_indices,
            },
        )

    def _build_fountain_complete_event(self) -> ReceiveEvent:
        assert self._fountain_decoder is not None

        full_data = self._fountain_decoder.get_file_data()
        file_size, expected_sha256, filename, content_offset = parse_fountain_metadata(
            full_data,
        )

        if file_size is not None and filename is not None and content_offset is not None:
            file_content = bytes(
                full_data[content_offset:content_offset + file_size],
            )
            sha256_ok = bool(
                expected_sha256 and verify_integrity(file_content, expected_sha256),
            )
            sha256_available = expected_sha256 is not None
        else:
            file_content = bytes(full_data)
            filename = f"received_{int(time.time())}.bin"
            file_size = len(file_content)
            sha256_ok = False
            sha256_available = False

        duration = self._elapsed()
        speed_mbps = (
            (file_size * 8) / duration / 1_000_000
            if duration > 0
            else 0
        )

        self._completed = True
        return ReceiveEvent(
            kind="complete",
            data={
                "protocol": "fountain",
                "filename": filename,
                "size": file_size,
                "sha256_ok": sha256_ok,
                "sha256_available": sha256_available,
                "duration_s": round(duration, 2),
                "speed_mbps": round(speed_mbps, 2),
                "bytes_received": self._fountain_bytes_received,
                "captured_bytes": self._fountain_bytes_received,
                "unique_bytes_received": self._fountain_unique_bytes_received,
                "useful_bytes_decoded": len(file_content) if sha256_available else None,
                "duplicate_droplets_received": (
                    self._fountain_droplets_received
                    - self._fountain_unique_droplets_received
                ),
                "chunks_decoded": len(self._fountain_decoder.chunks),
                "total_chunks": self._fountain_decoder.K,
                "droplets_received": self._fountain_droplets_received,
                "unique_droplets_received": (
                    self._fountain_unique_droplets_received
                ),
                "expected_droplets": self._fountain_expected_droplets,
                "file_content": file_content,
            },
        )
