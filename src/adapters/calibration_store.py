"""Versioned, best-effort storage of validated capture sampling geometry.

Entries are hints, never proof that a live HDMI path is still valid. A receiver
must validate fresh calibration frames before declaring a cached entry ready.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from hdmi_transfer.domain.models import ResolutionProfile

_VERSION = 1
_MAX_ENTRIES = 64
_LOCK = threading.Lock()

Sampling = tuple[int, int, float, float]


def calibration_key(
    *, device_identity: str, open_device: int | str, backend: int | None,
    profile: ResolutionProfile, capture_shape: tuple[int, ...],
) -> str:
    """Bind a hint to the actual capture path and incoming/encoded geometry."""
    context = {
        "device": device_identity, "source": str(open_device), "backend": backend,
        "profile": profile.name, "width": profile.width, "height": profile.height,
        "block_size": profile.block_size, "bpc": profile.bits_per_channel,
        "fps": profile.target_fps, "capture": list(capture_shape[:2]),
    }
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def _sampling(value: object) -> Sampling | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        return None
    ox, oy, sx, sy = value
    if not all(math.isfinite(v) for v in value):
        return None
    if ox != int(ox) or oy != int(oy) or not (0 <= ox <= 16384 and 0 <= oy <= 16384):
        return None
    if not (0.05 <= sx <= 4.0 and 0.05 <= sy <= 4.0):
        return None
    return int(ox), int(oy), float(sx), float(sy)


class CalibrationStore:
    """Atomic bounded cache; unreadable/corrupt entries never block a transfer."""

    def __init__(self, path: str | Path | None = None) -> None:
        state_dir = Path(os.environ.get("HDMI_TRANSFER_STATE_DIR", Path.home() / ".hdmi-transfer"))
        self.path = Path(path) if path is not None else state_dir / "calibration.json"

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != _VERSION:
                return {}
            entries = data.get("entries")
            return entries if isinstance(entries, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def load(self, key: str) -> Sampling | None:
        entry = self._read().get(key)
        return _sampling(entry.get("sampling")) if isinstance(entry, dict) else None

    def save(self, key: str, sampling: Sampling) -> bool:
        validated = _sampling(sampling)
        if validated is None:
            return False
        temporary: str | None = None
        try:
            with _LOCK:
                entries = self._read()
                entries[key] = {"sampling": validated, "saved_at": time.time()}
                # Preserve newest entries; discard malformed records as well.
                valid = [(k, v) for k, v in entries.items() if isinstance(v, dict)
                         and _sampling(v.get("sampling")) is not None
                         and isinstance(v.get("saved_at"), (int, float))]
                entries = dict(sorted(valid, key=lambda item: item[1]["saved_at"])[-_MAX_ENTRIES:])
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent,
                    prefix=".calibration-", suffix=".tmp", delete=False,
                ) as handle:
                    temporary = handle.name
                    json.dump({"version": _VERSION, "entries": entries}, handle, allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass
