# HDMI Exfil

## What This Is

A covert data transfer tool that encodes arbitrary data into HDMI video frames, transmitted from PC A to PC B via an Elgato 4K X capture card. The tool leaves zero traces on the source machine (no disk writes, no network activity) — HDMI is the only channel. Dual sender modes: browser-based (zero install on source) and Python (maximum performance).

## Core Value

Maximum throughput data transfer over HDMI without leaving any trace on the source machine.

## Requirements

### Validated

- ✓ Sequential frame encoding (3 bits/block, RGB binary) — Phase 1-2
- ✓ Fountain code encoding (LT codes, RSD, GE fallback) — Phase 2, 5
- ✓ Browser-based sender with zero install (sender.html) — Phase 3
- ✓ Python CLI sender/receiver with monitor detection — Phase 3, 6
- ✓ Shared constants.json (single source of truth) — Phase 3
- ✓ Metadata embedding (filename, SHA-256) — Phase 2
- ✓ Directory transfer via auto-zip — Phase 3
- ✓ Frame sync with magic numbers (0xDA7A seq, 0xF0C0 fountain) — Phase 2
- ✓ CRC32 per-frame integrity — Phase 2
- ✓ SHA-256 end-to-end file verification — Phase 2
- ✓ 3bpp RGB encoding (3x throughput vs 1bpp) — Phase 4
- ✓ Numba JIT XOR acceleration — Phase 4
- ✓ pygame-ce SDL2 high-FPS rendering — Phase 4
- ✓ Threaded capture with ring buffer — Phase 4
- ✓ Robust Soliton Distribution (<10% overhead) — Phase 5
- ✓ Gaussian elimination fallback decoder — Phase 5
- ✓ Resolution profiles (speed/balanced/quality) — Phase 6
- ✓ Calibration mode (SNR measurement) — Phase 6
- ✓ Benchmark mode (in-memory throughput) — Phase 6
- ✓ Progress reporting (speed, ETA, %) — Phase 6
- ✓ ~300 unit tests + property-based tests — Phase 1
- ✓ Hardware loopback validated (SNR 60dB, 110 KB/s) — Phase 1

### Active

- [ ] Interactive CLI console for sender (arrow-key menu)
- [ ] Interactive CLI console for receiver (arrow-key menu)
- [ ] Monorepo restructure with pip extras (`[sender]`, `[receiver]`)
- [ ] Clean sender/receiver/core module separation
- [ ] Project structure review and cleanup

### Out of Scope

- Encryption — HDMI is a physical channel, not needed
- Network communication — the entire point is zero network activity
- Full GUI application — interactive CLI menus are sufficient
- Steganography / hiding data in normal video — data is encoded as visible pixel blocks, not hidden
- Mobile device support — desktop-only tool
- Multi-file queue / batch transfers — one transfer at a time
- Web server for sender — sender.html stays standalone, CLI just opens it in browser

## Current Milestone: v1.1 Console Interactive & Restructure

**Goal:** Transform the CLI into interactive menu-driven consoles for sender and receiver, and restructure the monorepo so sender/receiver can be installed independently via pip extras.

**Target features:**
- Interactive sender console (InquirerPy arrow-key menu): send Python, send web (opens browser), calibrate, detect hardware, benchmark, settings
- Interactive receiver console: receive file, calibrate signal, detect capture card, last transfer stats, settings
- Monorepo with `pip install hdmi-exfil[sender]` / `[receiver]` / `[all]`
- Clean `src/core/`, `src/sender/`, `src/receiver/` separation
- Project structure review and cleanup

## Context

**v1.0 shipped:** Full working pipeline — sequential + fountain protocols, 3bpp RGB encoding, Numba JIT, pygame-ce renderer, threaded capture, RSD fountain codes, calibration, benchmarks, progress reporting. ~300 tests. Hardware-validated at 110 KB/s (balanced profile, SNR 60 dB).

**Current structure (flat src/):** All modules live under `src/` with pyproject.toml `package-dir` mapping `hdmi_exfil = "src"`. Works but mixes sender-only, receiver-only, and shared code.

**Hardware:** Elgato 4K X capture card. Tested in single-PC loopback (screen 2 duplicated to Elgato). Elgato at DirectShow index 1.

**Testing:** ~300 unit tests (pytest + hypothesis). 1 known failure (`test_xor_ops::test_fountain_decoder_with_numba`). 1 Node.js path issue on Windows (`test_rsd_cross_language`).

## Constraints

- **Hardware**: Elgato 4K X capture card is the transport medium — all encoding must be compatible with its capture characteristics
- **Zero trace**: Source PC (sender) must not write to disk or produce network traffic
- **One-way channel**: HDMI is sender→receiver only — no back-channel available, making fountain codes the ideal error correction strategy
- **Platform**: Sender must work in a browser (zero install) AND as Python script (max performance). Receiver is Python only.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Fountain codes for error correction | One-way HDMI channel has no back-channel for retries; fountain codes are rateless and work perfectly one-way | ✓ Good |
| Dual sender (browser + Python) | Browser = zero install on source; Python = max performance | ✓ Good |
| No encryption | Physical HDMI channel, security through air-gap | ✓ Good |
| 3-level test strategy | Unit → Loopback → Hardware allows development without 2-PC setup | ✓ Good |
| Multiple resolution modes | Different speed/reliability tradeoffs; benchmark to find optimal | ✓ Good |
| Monorepo + pip extras | Single repo with `[sender]`/`[receiver]` extras for independent install | — Pending |
| InquirerPy for interactive CLI | Arrow-key menus, minimal dependencies, good UX | — Pending |
| Core/sender/receiver split | Shared protocol code in core, UI-specific code in sender/receiver | — Pending |

---
*Last updated: 2026-03-02 after milestone v1.1 start*
