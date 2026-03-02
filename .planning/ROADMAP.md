# Roadmap: HDMI Exfil

## Overview

Transform the working HDMI data exfiltration prototype into a robust, high-performance tool. The journey starts by establishing a test safety net around the existing code, then adds protocol integrity (sync, checksums), restructures the architecture for clean module boundaries, unlocks maximum throughput via Numba JIT and pygame-ce, optimizes fountain code math for minimal overhead, and finishes with user-facing polish (profiles, calibration, progress). Each phase builds on the previous -- strict sequential dependency chain because tests gate refactoring, protocol gates architecture, architecture gates performance, and performance gates fountain tuning.

## Milestones

- Shipped **v1.0 MVP** - Phases 1-6 (shipped 2026-02-17)
- Active **v1.1 Console Interactive & Restructure** - Phases 7-9 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>Shipped v1.0 MVP (Phases 1-6) - SHIPPED 2026-02-17</summary>

- [x] **Phase 1: Test Foundation** - Establish test safety net around existing working prototype
- [x] **Phase 2: Protocol Foundation** - Add frame synchronization, integrity verification, and transfer lifecycle
- [x] **Phase 3: Architecture Refactor** - Restructure into clean src-layout package with protocol abstraction
- [x] **Phase 4: Performance Optimization** - Unlock maximum throughput with Numba JIT, pygame-ce, and threaded capture
- [x] **Phase 5: Fountain Code Optimization** - Tune fountain code math for minimal decoding overhead
- [x] **Phase 6: UX & Polish** - Resolution profiles, calibration mode, benchmarking, and progress reporting

</details>

### v1.1 Console Interactive & Restructure

- [x] **Phase 7: Monorepo Restructure** - Reorganize into core/sender/receiver subpackages with pip extras for independent installation
- [ ] **Phase 8: Interactive Sender Console** - Arrow-key menu-driven sender with file picker, profile/mode/monitor selection
- [ ] **Phase 9: Interactive Receiver Console** - Arrow-key menu-driven receiver with device selection, output config, and transfer stats

## Phase Details

<details>
<summary>Shipped v1.0 MVP (Phases 1-6) - SHIPPED 2026-02-17</summary>

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
**Plans:** 3 plans

Plans:
- [x] 01-01-PLAN.md -- Test infrastructure, fix broken loopback, sequential unit tests (TEST-01, TEST-02)
- [x] 01-02-PLAN.md -- PRNG cross-language vectors and fountain round-trip tests (TEST-03, TEST-04)
- [x] 01-03-PLAN.md -- Property-based tests and hardware loopback integration (TEST-05, TEST-06)

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
**Plans:** 5 plans

Plans:
- [x] 02-01-PLAN.md -- Sequential protocol header with magic 0xDA7A and CRC32 integrity (PROT-01, PROT-03)
- [x] 02-02-PLAN.md -- Fountain protocol header with magic 0xF0C0, CRC32, and chooseIndices bugfix (PROT-01, PROT-03)
- [x] 02-03-PLAN.md -- Transfer lifecycle START/DATA/END with SHA-256 verification (PROT-02, PROT-04, PROT-05)
- [x] 02-04-PLAN.md -- Fountain metadata extension with file_size and SHA-256 (PROT-04, PROT-05)
- [x] 02-05-PLAN.md -- Protocol routing by magic number and integration tests (PROT-06)

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
**Plans:** 7 plans

Plans:
- [x] 03-01-PLAN.md -- Package scaffold: pyproject.toml, constants.json, config.py, src-layout (ARCH-01, ARCH-05)
- [x] 03-02-PLAN.md -- Foundation modules: PRNG, EncodingProtocol ABC, sampler, metadata (ARCH-02, ARCH-08)
- [x] 03-03-PLAN.md -- Sequential protocol implementation + protocol registry (ARCH-03)
- [x] 03-04-PLAN.md -- Fountain protocol implementation + FountainDecoder migration (ARCH-04)
- [x] 03-05-PLAN.md -- I/O layer: cross-platform capture, display, monitors, file handling (ARCH-07, ARCH-08)
- [x] 03-06-PLAN.md -- CLI entry points + web sender build system (ARCH-05, ARCH-06, ARCH-09)
- [x] 03-07-PLAN.md -- Test migration: all imports to hdmi_exfil package, remove old hacks (ARCH-08)

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
**Plans:** 5 plans

Plans:
- [x] 04-01-PLAN.md -- 3bpp fountain encoding upgrade (PERF-01)
- [x] 04-02-PLAN.md -- Numba @njit XOR acceleration for FountainDecoder (PERF-03)
- [x] 04-03-PLAN.md -- pygame-ce SDL2 renderer + dependency update (PERF-04)
- [x] 04-04-PLAN.md -- Threaded capture with ring buffer + FPS reporting (PERF-05, PERF-06)
- [x] 04-05-PLAN.md -- Wire all components into CLI entry points (PERF-02)

### Phase 5: Fountain Code Optimization
**Goal**: Fountain decoding overhead drops from ~30% to ~5% for typical transfer sizes, making rateless coding practically free
**Depends on**: Phase 4
**Requirements**: FOUNT-01, FOUNT-02, FOUNT-03, FOUNT-04
**Success Criteria** (what must be TRUE):
  1. Degree distribution uses Robust Soliton Distribution (with configurable c and delta parameters) instead of the ad-hoc distribution -- benchmark shows lower overhead at K=10, K=100, K=1000
  2. When belief propagation stalls (common for small K), Gaussian elimination fallback decoder kicks in and recovers the data
  3. User can specify redundancy parameter per transfer (e.g., `--redundancy 1.05` for 5% overhead target)
  4. Measured decoding overhead is under 10% for K=100-1000 range (down from ~30% with current ad-hoc distribution)
**Plans**: 4 plans

Plans:
- [x] 05-01-PLAN.md -- RSD degree distribution module + Python integration (FOUNT-01)
- [x] 05-02-PLAN.md -- Gaussian elimination fallback decoder (FOUNT-02)
- [x] 05-03-PLAN.md -- JS sender RSD port + Python sender update + --redundancy CLI (FOUNT-01, FOUNT-03)
- [x] 05-04-PLAN.md -- Overhead benchmarks + parameter tuning (FOUNT-04)

### Phase 6: UX & Polish
**Goal**: Users can run transfers without understanding encoding internals -- named profiles, auto-calibration, benchmarking, and live progress make the tool accessible
**Depends on**: Phase 5
**Requirements**: UX-01, UX-02, UX-03, UX-04
**Success Criteria** (what must be TRUE):
  1. User selects a named resolution profile (`--profile speed`, `--profile balanced`, `--profile quality`) and all encoding parameters auto-configure for that mode
  2. Calibration mode displays a known test pattern on sender, receiver analyzes it and reports alignment offset, SNR, and recommended block size
  3. Benchmarking mode runs an automated throughput measurement and outputs results as JSON (frames/sec, bytes/sec, overhead percentage, error rate)
  4. During active transfer, receiver displays real-time progress: frames received, decode percentage, transfer speed in bytes/sec, and estimated time remaining
**Plans**: 4 plans

Plans:
- [x] 06-01-PLAN.md -- ResolutionProfile dataclass + protocol constructor injection (UX-01 core)
- [x] 06-02-PLAN.md -- JS sender 3bpp encoding upgrade (deferred blocker)
- [x] 06-03-PLAN.md -- CLI --profile flag + ProgressTracker + progress reporting (UX-01 CLI, UX-04)
- [x] 06-04-PLAN.md -- Calibration + benchmarking CLI modes (UX-02, UX-03)

</details>

### Phase 7: Monorepo Restructure
**Goal**: The codebase is reorganized into core/sender/receiver subpackages so sender and receiver can be installed independently with minimal dependencies
**Depends on**: Phase 6 (v1.0 complete)
**Requirements**: STRUCT-01, STRUCT-02, STRUCT-03, STRUCT-04, STRUCT-05, STRUCT-06, STRUCT-07
**Success Criteria** (what must be TRUE):
  1. Source tree is organized as `src/hdmi_exfil/core/`, `src/hdmi_exfil/sender/`, `src/hdmi_exfil/receiver/` with core containing only shared protocol, encoding, and file handling code -- no hardware dependencies in core
  2. Running `pip install hdmi-exfil[sender]` in a clean virtualenv installs pygame-ce and screeninfo but not opencv-python, and the sender CLI commands work
  3. Running `pip install hdmi-exfil[receiver]` in a clean virtualenv installs opencv-python but not pygame-ce, and the receiver CLI commands work
  4. Running `pip install hdmi-exfil` or `hdmi-exfil[all]` installs all dependencies and all CLI commands work
  5. All four existing CLI commands (`hdmi-send`, `hdmi-recv`, `hdmi-calibrate`, `hdmi-bench`) produce identical behavior after the restructure -- no user-visible changes
  6. All existing tests pass after the restructure with zero regressions
**Plans**: 3 plans

Plans:
- [x] 07-01-PLAN.md -- Replace cv2.resize with np.repeat in protocol encoding (STRUCT-06)
- [x] 07-02-PLAN.md -- Move files into core/sender/receiver subpackages with shims (STRUCT-01)
- [x] 07-03-PLAN.md -- Update pyproject.toml with extras and verify CLI/tests (STRUCT-02, STRUCT-03, STRUCT-04, STRUCT-05, STRUCT-07)

### Phase 8: Interactive Sender Console
**Goal**: Users can operate the sender through an interactive arrow-key menu instead of memorizing CLI flags -- the menu collects all parameters and delegates to the existing send pipeline
**Depends on**: Phase 7
**Requirements**: SEND-01, SEND-02, SEND-03, SEND-04, SEND-05, SEND-06, SEND-07, SEND-08
**Success Criteria** (what must be TRUE):
  1. Running `hdmi-sender` launches an interactive console with an arrow-key navigable main menu listing all sender actions (Send Python, Send Browser, Calibrate, Detect hardware, Benchmark, Quit)
  2. User can select a file to send via interactive file path prompt with tab-completion, choose a resolution profile, encoding mode, and target monitor -- all via arrow-key selection from detected options
  3. After any action completes (send, calibrate, benchmark, detect), the user returns to the main menu and can pick another action without restarting
  4. Pressing Ctrl-C at any prompt or during any action exits cleanly without a Python traceback
  5. The interactive console delegates to the same send/calibrate/benchmark functions as the existing CLI commands -- no duplicated encoding or display logic
**Plans**: 2 plans

Plans:
- [ ] 08-01-PLAN.md -- Extract run_send() from send.py + add InquirerPy dependency (SEND-01, SEND-05)
- [ ] 08-02-PLAN.md -- Interactive console module with menu, prompts, dispatch, tests (SEND-01 through SEND-08)

### Phase 9: Interactive Receiver Console
**Goal**: Users can operate the receiver through an interactive arrow-key menu instead of memorizing CLI flags -- the menu collects all parameters and delegates to the existing receive pipeline
**Depends on**: Phase 7 (restructure); Phase 8 (pattern established)
**Requirements**: RECV-01, RECV-02, RECV-03, RECV-04, RECV-05, RECV-06, RECV-07
**Success Criteria** (what must be TRUE):
  1. Running `hdmi-receiver` launches an interactive console with an arrow-key navigable main menu listing all receiver actions (Receive file, Calibrate signal, Detect capture card, Last transfer stats, Settings, Quit)
  2. User can select a capture device from detected devices via arrow-key prompt, choose a resolution profile, and configure the output directory -- all interactively
  3. After any action completes (receive, calibrate, detect), the user returns to the main menu and can pick another action without restarting
  4. Pressing Ctrl-C at any prompt or during any action exits cleanly without a Python traceback
  5. The interactive console delegates to the same receive/calibrate functions as the existing CLI commands -- no duplicated capture or decode logic

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 7 -> 8 -> 9

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Test Foundation | v1.0 | 3/3 | Complete | 2026-02-16 |
| 2. Protocol Foundation | v1.0 | 5/5 | Complete | 2026-02-16 |
| 3. Architecture Refactor | v1.0 | 7/7 | Complete | 2026-02-16 |
| 4. Performance Optimization | v1.0 | 5/5 | Complete | 2026-02-16 |
| 5. Fountain Code Optimization | v1.0 | 4/4 | Complete | 2026-02-17 |
| 6. UX & Polish | v1.0 | 4/4 | Complete | 2026-02-17 |
| 7. Monorepo Restructure | v1.1 | 3/3 | Complete | 2026-03-02 |
| 8. Interactive Sender Console | v1.1 | 0/2 | Planned | - |
| 9. Interactive Receiver Console | v1.1 | 0/? | Not started | - |

---
*Roadmap created: 2026-02-16*
*v1.1 phases added: 2026-03-02*
*Last updated: 2026-03-02 -- Phase 7 complete (3/3 plans). Ready for Phase 8 (Sender Console)*
