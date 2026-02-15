# HDMI Exfil

## What This Is

A covert data transfer tool that encodes arbitrary data into HDMI video frames, transmitted from PC A to PC B via an Elgato 4K X capture card. The tool leaves zero traces on the source machine (no disk writes, no network activity) — HDMI is the only channel. Dual sender modes: browser-based (zero install on source) and Python (maximum performance).

## Core Value

Maximum throughput data transfer over HDMI without leaving any trace on the source machine.

## Requirements

### Validated

- ✓ Sequential frame encoding (1-bit per RGB channel, 3 bits/block) — existing (`sender.py` / `receiver.py`)
- ✓ Fountain code encoding (LT codes with belief propagation decoder) — existing (`sender.html` / `receiver_fountain.py`)
- ✓ Browser-based sender with zero install — existing (`sender.html`)
- ✓ Python CLI sender with monitor detection — existing (`sender.py`)
- ✓ Python CLI receivers for both modes — existing (`receiver.py`, `receiver_fountain.py`)
- ✓ Shared configuration constants — existing (`common.py`)
- ✓ Metadata embedding (filename preservation) — existing
- ✓ Directory transfer via auto-zip — existing (`sender.py`)

### Active

- [ ] Maximize transfer speed — push toward theoretical HDMI bandwidth limits
- [ ] Multi-resolution support — 4K@30fps, 1080p@60fps, 1080p@240fps modes with benchmarks
- [ ] Professional project architecture — clean module structure, separation of concerns
- [ ] 3-level test strategy — unit tests (encode/decode in memory), loopback (Elgato on same PC), hardware (2 PCs)
- [ ] Fountain code optimization — tune degree distribution, chunk size, PRNG for max throughput
- [ ] Cross-platform sender — remove Windows-only dependencies (ctypes.windll)
- [ ] Robust frame synchronization — reliable start/end detection, calibration frames
- [ ] Progress reporting — real-time speed, ETA, completion percentage
- [ ] File integrity verification — checksum validation after transfer

### Out of Scope

- Encryption — HDMI is a physical channel, not needed for v1
- Network communication — the entire point is zero network activity
- GUI application — CLI + browser sender is sufficient
- Steganography / hiding data in normal video — data is encoded as visible pixel blocks, not hidden
- Mobile device support — desktop-only tool
- Multi-file queue / batch transfers — one transfer at a time

## Context

**Existing codebase:** Working prototype with two encoding modes (sequential and fountain). The fountain mode (sender.html + receiver_fountain.py) is the more advanced path — rateless erasure coding means the sender doesn't need acknowledgment from the receiver, which is perfect for the one-way HDMI channel.

**Hardware:** Elgato 4K X capture card. Supports up to 4K@30fps passthrough and 1080p@240fps capture. Higher framerate = more data throughput since each frame carries a fixed payload. The sweet spot needs benchmarking.

**Theoretical bandwidth:**
- 1080p@240fps: 1920×1080 pixels × 240 frames = ~497M pixels/sec
- With 8×8 blocks, 3 bits/block: ~2.8M blocks/frame × 3 bits = ~1.05 MB/frame → ~252 MB/s raw
- With 1 bit/block (fountain mode): ~350 KB/frame → ~84 MB/s raw
- Actual throughput depends on: capture card processing, frame loss rate, fountain code overhead, sync headers

**Current limitations identified:**
- Windows-only (`ctypes.windll`, `cv2.CAP_DSHOW`)
- No test framework — manual `print()`-based verification
- Duplicated constants between `common.py` and `sender.html`
- No checksums on transferred data
- Bare `except Exception: pass` in fountain receiver
- sender.html fountain code uses 1 bit/block vs sender.py using 3 bits/block (potential 3x throughput improvement)

**Testing approach (3 levels):**
1. **Unit tests** — encode/decode in pure memory, no hardware needed. Validate bit packing, fountain encode/decode, metadata handling.
2. **Loopback tests** — Elgato plugged into same PC (HDMI out → capture card in). Tests full pipeline including capture card behavior.
3. **Hardware tests** — Real 2-PC setup. Validates end-to-end in production conditions.

## Constraints

- **Hardware**: Elgato 4K X capture card is the transport medium — all encoding must be compatible with its capture characteristics
- **Zero trace**: Source PC (sender) must not write to disk or produce network traffic
- **One-way channel**: HDMI is sender→receiver only — no back-channel available, making fountain codes the ideal error correction strategy
- **Platform**: Sender must work in a browser (zero install) AND as Python script (max performance). Receiver is Python only.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Fountain codes for error correction | One-way HDMI channel has no back-channel for retries; fountain codes are rateless and work perfectly one-way | — Pending |
| Dual sender (browser + Python) | Browser = zero install on source; Python = max performance | — Pending |
| No encryption | Physical HDMI channel, security through air-gap | — Pending |
| 3-level test strategy | Unit → Loopback → Hardware allows development without 2-PC setup | — Pending |
| Multiple resolution modes | Different speed/reliability tradeoffs; benchmark to find optimal | — Pending |

---
*Last updated: 2026-02-16 after initialization*
