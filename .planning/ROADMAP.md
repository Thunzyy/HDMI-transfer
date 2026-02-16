# Roadmap: HDMI Exfil

## Overview

Transform the working HDMI data exfiltration prototype into a robust, high-performance tool. The journey starts by establishing a test safety net around the existing code, then adds protocol integrity (sync, checksums), restructures the architecture for clean module boundaries, unlocks maximum throughput via Numba JIT and pygame-ce, optimizes fountain code math for minimal overhead, and finishes with user-facing polish (profiles, calibration, progress). Each phase builds on the previous -- strict sequential dependency chain because tests gate refactoring, protocol gates architecture, architecture gates performance, and performance gates fountain tuning.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Test Foundation** - Establish test safety net around existing working prototype
- [ ] **Phase 2: Protocol Foundation** - Add frame synchronization, integrity verification, and transfer lifecycle
- [ ] **Phase 3: Architecture Refactor** - Restructure into clean src-layout package with protocol abstraction
- [ ] **Phase 4: Performance Optimization** - Unlock maximum throughput with Numba JIT, pygame-ce, and threaded capture
- [ ] **Phase 5: Fountain Code Optimization** - Tune fountain code math for minimal decoding overhead
- [ ] **Phase 6: UX & Polish** - Resolution profiles, calibration mode, benchmarking, and progress reporting

## Phase Details

### Phase 1: Test Foundation
**Goal**: Developers can verify encode/decode correctness and PRNG synchronization without manual testing or hardware
**Depends on**: Nothing (first phase)
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):
  1. Running `pytest` executes all unit tests and they pass -- sequential encode/decode round-trips produce identical output for arbitrary binary inputs
  2. Running `pytest` executes fountain encode/decode round-trips that recover original data from sufficient encoded symbols in memory (no hardware)
  3. PRNG test vectors confirm Python SplitMix32 and JavaScript SplitMix32 produce identical output for 1000+ seeds
  4. Loopback test (Elgato on same PC) successfully transfers a file through the full pipeline and verifies byte-for-byte match
  5. Property-based tests (hypothesis) pass for encode/decode with randomized binary data of varying sizes
**Plans**: TBD

Plans:
- [ ] 01-01: TBD
- [ ] 01-02: TBD
- [ ] 01-03: TBD
- [ ] 01-04: TBD
- [ ] 01-05: TBD

### Phase 2: Protocol Foundation
**Goal**: Every frame is self-describing and integrity-verified -- receiver can detect corruption, distinguish protocols, and verify complete file transfers
**Depends on**: Phase 1
**Requirements**: PROT-01, PROT-02, PROT-03, PROT-04, PROT-05, PROT-06
**Success Criteria** (what must be TRUE):
  1. Receiver rejects noise/idle frames and only processes frames containing the correct magic number in the header
  2. Receiver correctly handles the full transfer lifecycle: detects START frame, processes DATA frames in sequence, and finalizes on END frame
  3. Receiver detects and reports per-frame corruption via CRC32 mismatch (corrupted frames are flagged, not silently accepted)
  4. After reassembly, receiver computes SHA-256 of the received file and compares it against the hash embedded in the START frame metadata -- mismatch produces a clear error
  5. Receiver distinguishes sequential protocol frames (magic 0xDA7A) from fountain protocol frames (magic 0xF0C0) and routes to the correct decoder
**Plans**: TBD

Plans:
- [ ] 02-01: TBD
- [ ] 02-02: TBD
- [ ] 02-03: TBD
- [ ] 02-04: TBD
- [ ] 02-05: TBD

### Phase 3: Architecture Refactor
**Goal**: Codebase is a proper Python package with clean module boundaries, protocol abstraction, shared constants, and cross-platform support
**Depends on**: Phase 2
**Requirements**: ARCH-01, ARCH-02, ARCH-03, ARCH-04, ARCH-05, ARCH-06, ARCH-07, ARCH-08, ARCH-09
**Success Criteria** (what must be TRUE):
  1. Project installs via `pip install -e .` with pyproject.toml and exposes CLI entry points (`hdmi-send`, `hdmi-recv` or similar) that work
  2. Sequential and fountain protocols both implement the same EncodingProtocol ABC and can be swapped via CLI flag without code changes
  3. A single constants.json file is the source of truth for all encoding parameters -- Python reads it directly, and a build script generates sender.html with those values injected
  4. Receiver runs on Linux (V4L2), Windows (DirectShow), and macOS (AVFoundation) without code changes -- capture backend is auto-detected
  5. Source tree follows src-layout with separated modules: protocols/, capture/, display/, file_handling/ -- no circular imports, each module testable in isolation
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD
- [ ] 03-03: TBD
- [ ] 03-04: TBD
- [ ] 03-05: TBD
- [ ] 03-06: TBD
- [ ] 03-07: TBD

### Phase 4: Performance Optimization
**Goal**: Transfer throughput approaches hardware limits -- 240fps rendering, parallel capture, and JIT-accelerated encoding are operational
**Depends on**: Phase 3
**Requirements**: PERF-01, PERF-02, PERF-03, PERF-04, PERF-05, PERF-06
**Success Criteria** (what must be TRUE):
  1. Fountain mode uses 3 bits per block (RGB binary encoding) instead of 1 bit, tripling per-frame data capacity
  2. Python fountain sender exists and combines fountain codes with 3bpp encoding for maximum throughput path
  3. Fountain XOR loops run via Numba @njit -- measurable speedup over pure Python (target 100x+ on encode/decode hot path)
  4. Sender renders frames via pygame-ce SDL2 at the monitor's native refresh rate (measured >120fps on 240Hz display, replacing cv2.imshow ceiling of ~80fps)
  5. Capture pipeline runs in a dedicated thread with ring buffer -- actual captured FPS is measured and reported, no frames dropped due to blocking .read() calls
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD
- [ ] 04-03: TBD
- [ ] 04-04: TBD
- [ ] 04-05: TBD
- [ ] 04-06: TBD

### Phase 5: Fountain Code Optimization
**Goal**: Fountain decoding overhead drops from ~30% to ~5% for typical transfer sizes, making rateless coding practically free
**Depends on**: Phase 4
**Requirements**: FOUNT-01, FOUNT-02, FOUNT-03, FOUNT-04
**Success Criteria** (what must be TRUE):
  1. Degree distribution uses Robust Soliton Distribution (with configurable c and delta parameters) instead of the ad-hoc distribution -- benchmark shows lower overhead at K=10, K=100, K=1000
  2. When belief propagation stalls (common for small K), Gaussian elimination fallback decoder kicks in and recovers the data
  3. User can specify redundancy parameter per transfer (e.g., `--redundancy 1.05` for 5% overhead target)
  4. Measured decoding overhead is under 10% for K=100-1000 range (down from ~30% with current ad-hoc distribution)
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD
- [ ] 05-03: TBD
- [ ] 05-04: TBD
- [ ] 05-05: TBD

### Phase 6: UX & Polish
**Goal**: Users can run transfers without understanding encoding internals -- named profiles, auto-calibration, benchmarking, and live progress make the tool accessible
**Depends on**: Phase 5
**Requirements**: UX-01, UX-02, UX-03, UX-04
**Success Criteria** (what must be TRUE):
  1. User selects a named resolution profile (`--profile speed`, `--profile balanced`, `--profile quality`) and all encoding parameters auto-configure for that mode
  2. Calibration mode displays a known test pattern on sender, receiver analyzes it and reports alignment offset, SNR, and recommended block size
  3. Benchmarking mode runs an automated throughput measurement and outputs results as JSON (frames/sec, bytes/sec, overhead percentage, error rate)
  4. During active transfer, receiver displays real-time progress: frames received, decode percentage, transfer speed in bytes/sec, and estimated time remaining
**Plans**: TBD

Plans:
- [ ] 06-01: TBD
- [ ] 06-02: TBD
- [ ] 06-03: TBD
- [ ] 06-04: TBD
- [ ] 06-05: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Test Foundation | 0/5 | Not started | - |
| 2. Protocol Foundation | 0/5 | Not started | - |
| 3. Architecture Refactor | 0/7 | Not started | - |
| 4. Performance Optimization | 0/6 | Not started | - |
| 5. Fountain Code Optimization | 0/5 | Not started | - |
| 6. UX & Polish | 0/5 | Not started | - |

---
*Roadmap created: 2026-02-16*
*Last updated: 2026-02-16*
