# Requirements: HDMI Exfil

**Defined:** 2026-02-16
**Core Value:** Maximum throughput data transfer over HDMI without leaving any trace on the source machine.

## v1 Requirements

### Test Foundation

- [x] **TEST-01**: Fix broken loopback test (test_loopback.py has wrong function signatures)
- [x] **TEST-02**: Unit tests for sequential encode/decode round-trips in memory (no hardware)
- [x] **TEST-03**: Unit tests for fountain encode/decode round-trips in memory (no hardware)
- [x] **TEST-04**: PRNG cross-language test vectors — verify Python and JS SplitMix32 produce identical output for 1000+ seeds
- [x] **TEST-05**: Loopback integration tests using Elgato capture card on same PC
- [x] **TEST-06**: Property-based tests (hypothesis) for encode/decode with arbitrary binary data

### Protocol & Integrity

- [x] **PROT-01**: Frame synchronization via magic number in frame header to distinguish data from noise/idle
- [x] **PROT-02**: Frame type system — IDLE, START, DATA, END frame types for transfer lifecycle
- [x] **PROT-03**: Per-frame CRC32 for immediate corruption detection
- [x] **PROT-04**: Extended metadata in START frame — filename, file size, SHA-256 hash
- [x] **PROT-05**: File-level SHA-256 integrity verification on receiver after reassembly
- [x] **PROT-06**: Magic number differentiation between sequential (0xDA7A) and fountain (0xF0C0) protocols

### Architecture

- [x] **ARCH-01**: src-layout Python package with pyproject.toml and proper module hierarchy
- [x] **ARCH-02**: EncodingProtocol ABC with encode_frame/decode_frame interface (strategy pattern)
- [x] **ARCH-03**: Sequential protocol implementation inheriting from EncodingProtocol ABC
- [x] **ARCH-04**: Fountain protocol implementation inheriting from EncodingProtocol ABC
- [x] **ARCH-05**: constants.json as single source of truth shared between Python and JavaScript
- [x] **ARCH-06**: Build script to inject constants.json values into sender.html at generation time
- [x] **ARCH-07**: Cross-platform capture backend — auto-detect V4L2 (Linux), DirectShow (Windows), AVFoundation (macOS)
- [x] **ARCH-08**: Separated modules: capture/, display/, protocols/, file_handling/
- [x] **ARCH-09**: CLI entry points for sender and receiver via pyproject.toml scripts

### Performance

- [x] **PERF-01**: 3-bit per block encoding for fountain mode (upgrade from 1bpp to 3bpp RGB binary)
- [x] **PERF-02**: Python fountain sender combining fountain codes + 3bpp encoding
- [x] **PERF-03**: Numba @njit acceleration for fountain XOR loops (target 100x+ speedup)
- [x] **PERF-04**: pygame-ce SDL2 display replacing cv2.imshow (unlock 240fps rendering)
- [x] **PERF-05**: Threaded capture pipeline with ring buffer (unlock actual high-FPS capture)
- [x] **PERF-06**: Actual FPS measurement and reporting during capture

### Fountain Optimization

- [x] **FOUNT-01**: Robust Soliton Distribution replacing ad-hoc degree distribution
- [x] **FOUNT-02**: Gaussian elimination fallback decoder for small K when belief propagation stalls
- [x] **FOUNT-03**: Configurable redundancy parameter per transfer
- [x] **FOUNT-04**: Overhead reduction from ~30% to ~5% for typical K values (1-1000)

### UX & Polish

- [ ] **UX-01**: Resolution profiles — named presets (1080p@240fps "speed", 1080p@60fps "balanced", 4K@30fps "quality")
- [ ] **UX-02**: Calibration mode — sender displays known pattern, receiver analyzes alignment, SNR, optimal block size
- [ ] **UX-03**: Benchmarking mode — automated throughput measurement with JSON output
- [ ] **UX-04**: Progress reporting — real-time frames received, decode %, speed (bytes/sec), ETA

## v2 Requirements

### Session Management

- **SESS-01**: Session ID in frame headers for multi-transfer support without restart
- **SESS-02**: Automatic new-session detection on receiver

### Adaptive Encoding

- **ADAPT-01**: Adaptive block size based on calibration results
- **ADAPT-02**: Multi-level encoding (4+ bits/channel) if capture card supports it

## Out of Scope

| Feature | Reason |
|---------|--------|
| Encryption | Physical air-gap channel; encrypt files before sending if needed |
| Back-channel communication | Defeats zero-trace purpose; fountain codes handle reliability |
| Steganography | Visible pixel encoding is the design; hiding data in video is a different tool |
| GUI application | CLI + browser sender is sufficient |
| Audio channel encoding | Negligible bandwidth vs video (~1.5 Mbps vs ~250 MB/s raw) |
| Raptor/RaptorQ codes | Patent concerns (Qualcomm), marginal improvement for K<1000; LT + RSD sufficient |
| Mobile support | Desktop-only tool |
| Real-time compression | Compress files before sending; transport treats data as opaque bytes |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| TEST-01 | Phase 1 | Complete |
| TEST-02 | Phase 1 | Complete |
| TEST-03 | Phase 1 | Complete |
| TEST-04 | Phase 1 | Complete |
| TEST-05 | Phase 1 | Complete |
| TEST-06 | Phase 1 | Complete |
| PROT-01 | Phase 2 | Complete |
| PROT-02 | Phase 2 | Complete |
| PROT-03 | Phase 2 | Complete |
| PROT-04 | Phase 2 | Complete |
| PROT-05 | Phase 2 | Complete |
| PROT-06 | Phase 2 | Complete |
| ARCH-01 | Phase 3 | Complete |
| ARCH-02 | Phase 3 | Complete |
| ARCH-03 | Phase 3 | Complete |
| ARCH-04 | Phase 3 | Complete |
| ARCH-05 | Phase 3 | Complete |
| ARCH-06 | Phase 3 | Complete |
| ARCH-07 | Phase 3 | Complete |
| ARCH-08 | Phase 3 | Complete |
| ARCH-09 | Phase 3 | Complete |
| PERF-01 | Phase 4 | Complete |
| PERF-02 | Phase 4 | Complete |
| PERF-03 | Phase 4 | Complete |
| PERF-04 | Phase 4 | Complete |
| PERF-05 | Phase 4 | Complete |
| PERF-06 | Phase 4 | Complete |
| FOUNT-01 | Phase 5 | Complete |
| FOUNT-02 | Phase 5 | Complete |
| FOUNT-03 | Phase 5 | Complete |
| FOUNT-04 | Phase 5 | Complete |
| UX-01 | Phase 6 | Pending |
| UX-02 | Phase 6 | Pending |
| UX-03 | Phase 6 | Pending |
| UX-04 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 35 total
- Mapped to phases: 35
- Unmapped: 0

---
*Requirements defined: 2026-02-16*
*Last updated: 2026-02-17 -- Phase 5 requirements complete*
