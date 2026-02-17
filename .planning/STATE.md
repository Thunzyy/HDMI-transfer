# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-16)

**Core value:** Maximum throughput data transfer over HDMI without leaving any trace on the source machine.
**Current focus:** Phase 6 UX and Polish

## Current Position

Phase: 6 of 6 (UX and Polish)
Plan: 4 of 4 in current phase
Status: Phase complete -- ALL PHASES COMPLETE
Last activity: 2026-02-17 -- Completed 06-04-PLAN.md (Calibration and Benchmark CLI)

Progress: [████████████████████████████████] 28/28 (100%)

## Performance Metrics

**Velocity:**
- Total plans completed: 28
- Average duration: 5min
- Total execution time: 149min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-test-foundation | 3/3 | 45min | 15min |
| 02-protocol-foundation | 5/5 | 19min | 4min |
| 03-architecture-refactor | 7/7 | 24min | 3min |
| 04-performance-optimization | 5/5 | 12min | 2min |
| 05-fountain-code-optimization | 4/4 | 35min | 9min |
| 06-ux-polish | 4/4 | 14min | 4min |

**Recent Trend:**
- Last 5 plans: 05-04 (10min), 06-02 (2min), 06-01 (4min), 06-03 (4min), 06-04 (4min)
- Trend: UX plans executing quickly (2-4min). All phases complete.

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 6-phase strict sequential dependency chain (tests -> protocol -> architecture -> performance -> fountain -> UX)
- [01-01]: ctypes.wintypes imports fine on Linux -- no sender.py patching needed for test imports
- [01-01]: Empty data encode/decode returns (None, None, None, None) -- tested and confirmed as edge case
- [01-02]: PRNG |0 operator confirmed harmless -- Python/JS produce identical output for 1028 seeds
- [02-01]: Header format >HBIIH: magic(2)+type(1)+index(4)+total(4)+data_len(2)=13 pre-CRC + 4 CRC32 = 17 bytes
- [02-01]: CRC32 computed over pre-CRC header + payload; frame_type defaults to FRAME_TYPE_DATA for backward compat
- [02-01]: BYTES_PER_FRAME auto-recalculated from 12138 to 12133 (5 fewer payload bytes per frame)
- [02-02]: chooseIndices bugfix applied -- degree capped to min(degree, K) in both JS and Python
- [02-02]: Fountain header: magic(2)+seed(4)+K(2)+crc32(4)=12 bytes, PAYLOAD_SIZE=4038
- [02-03]: decode_frame_full (5-tuple with frame_type) added alongside decode_frame (4-tuple)
- [02-03]: START payload: [4B file_size][32B SHA-256][2B name_len][NB name]
- [02-04]: Fountain metadata format matches sequential START: [4B file_size][32B SHA-256][2B name_len][NB name][content]
- [02-05]: route_frame uses lazy import of receiver_fountain constants to avoid circular imports
- [03-01]: Build backend: setuptools.build_meta with src-layout packaging
- [03-01]: constants.json stores magic numbers as decimal (55930, 61632) for cross-language compat
- [03-01]: Frame types in config.py not constants.json (protocol-specific, not encoding params)
- [03-02]: choose_indices returns frozenset (hashable for caching), not set
- [03-02]: Leaf modules (prng, sampler, metadata) import only stdlib+numpy, never config
- [03-02]: FrameResult is frozen+slots dataclass for immutability and memory efficiency
- [03-02]: cv2 import is lazy in sampler (only needed for resize path)
- [03-04]: Fountain constants (FOUNT_HEADER_FMT, PAYLOAD_SIZE) in fountain.py, not config.py (protocol-specific)
- [03-04]: cv2 lazy import in FountainProtocol.encode_frame (matches sampler pattern)
- [03-03]: TransferState uses Enum with auto() instead of plain class with string constants (type safety)
- [03-03]: decode_frame_legacy wraps decode_frame for backward-compat 4-tuple returns
- [03-03]: encode_frame omits sys.stdout progress output (UI concern, belongs in CLI layer)
- [03-04]: Protocol registry includes both sequential and fountain via PROTOCOLS dict + get_protocol() factory
- [03-05]: CaptureSource tries preferred backend first, falls back to CAP_ANY
- [03-05]: get_monitors() lazy imports screeninfo with broad except -- never crashes on headless/CI
- [03-05]: write_output sanitizes filename with os.path.basename (prevents path traversal)
- [03-05]: Context manager pattern on all I/O wrappers (CaptureSource, FrameRenderer)
- [03-06]: CLI modules are thin orchestrators -- zero encoding/decoding logic, just wiring
- [03-06]: Fountain magic rendered as hex literal (0xF0C0) in JS; decimal (61632) in JSON
- [03-06]: Build script uses importlib.resources for package-relative constants.json access
- [03-06]: Auto-detect mode tries sequential decode first (0xDA7A), falls back to fountain (0xF0C0)
- [03-07]: route_frame re-implemented as test-local helper (not added to package -- test-only concern)
- [03-07]: choose_indices frozenset->set wrapper in test helpers for mutable-set compatibility
- [03-07]: All test imports use from hdmi_exfil.* exclusively; old flat modules no longer tested
- [04-01]: Fountain PAYLOAD_SIZE updated from 4038 to 12138 (3x via RGB binary encoding)
- [04-01]: Fountain encode/decode now uses identical 3bpp pattern as SequentialProtocol
- [04-01]: FountainDecoder unchanged -- operates on raw bytes, not pixels; 3bpp is transparent to it
- [04-04]: ThreadedCapture uses duck typing (no CaptureSource import) -- wraps any read()->(bool, frame) object
- [04-04]: Default buffer_size=16 (~96MB at 1080p) balances latency vs memory
- [04-04]: FPSReporter uses perf_counter_ns for nanosecond-precision monotonic timing
- [04-04]: actual_fps returns 0.0 when window is stale (>2s) to avoid misleading numbers
- [04-03]: pygame lazy import inside PygameRenderer.__init__ so module importable in headless/CI
- [04-03]: opencv-python replaced with opencv-python-headless to avoid SDL2 conflicts with pygame-ce
- [04-03]: PygameRenderer returns 255 for no-key (matching FrameRenderer convention for drop-in replacement)
- [04-03]: numba pre-installed alongside pygame-ce to avoid double-reinstall for plan 04-02
- [04-02]: xor_into uses element-wise @njit loop (not numpy vectorized) for nogil GIL release during threaded capture
- [04-02]: bytearray->np.ndarray conversion at add_droplet boundary; public API unchanged (accepts bytes|bytearray)
- [04-02]: FountainDecoder.chunks now dict[int, np.ndarray] -- get_file_data uses .tobytes() for output
- [04-05]: Pause/end screens use solid-color numpy frames (no cv2.putText) for renderer-agnostic operation
- [04-05]: Fountain chunks stored as np.ndarray list for direct Numba xor_into compatibility
- [04-05]: Receive loops sleep 1ms on empty buffer reads to avoid CPU spin with ThreadedCapture
- [04-05]: FPS reporting at 2s intervals appended to progress lines during reception
- [04-05]: _run_receiver helper extracts mode dispatch for clean threaded/direct paths
- [05-01]: Lazy import of degree module in prng.py to break circular dependency (prng -> degree -> protocols.__init__ -> fountain -> prng)
- [05-01]: bisect.bisect_left for O(log K) CDF sampling in sample_degree
- [05-01]: CDF[-1] forced to exactly 1.0 to prevent floating-point drift
- [05-01]: JS cross-language choose_indices vectors deferred to plan 05-03 when JS is updated to RSD
- [05-02]: GE uses dense numpy uint8 matrix with XOR row operations (fast for K < 1000)
- [05-02]: Full RREF in one pass (forward elimination eliminates ALL rows, not just below pivot)
- [05-02]: Auto-trigger GE after each add_droplet with lightweight n_unresolved >= n_unknown guard
- [05-02]: GE copies unresolved droplet data to avoid mutating decoder state on failure
- [05-02]: resolve_chunk() as shared entry point for both BP and GE recovered chunks
- [05-03]: --fountain-redundancy float flag separate from --redundancy int (sequential frame repeat)
- [05-03]: Python sender uses choose_indices() directly (single-source-of-truth via degree.py)
- [05-03]: JS sampleDegree uses (lo+hi)>>1 binary search matching Python bisect.bisect_left
- [05-03]: JS 3bpp encoding deferred to UX phase (RSD math is encoding-independent)
- [05-04]: c=0.1, delta=0.05 defaults unchanged -- already meet <10% overhead for K>=100
- [05-04]: Overhead benchmarks use 100-byte payload (overhead is payload-size-independent)
- [05-04]: Statistical averaging (20 runs/K) with seeded numpy PRNG for reproducibility
- [05-04]: @pytest.mark.slow registered in pyproject.toml for K>=500 benchmarks
- [06-02]: JS drawBits uses ABGR uint32 packing (0xFF000000 | B<<16 | G<<8 | R) for 3bpp RGB encoding
- [06-02]: JS bit order R,G,B per block matches Python np.unpackbits MSB-first + reshape((blocks,3))
- [06-01]: ResolutionProfile is additive -- existing module-level constants remain independent (not aliased to DEFAULT_PROFILE)
- [06-01]: _FOUNT_HEADER_SIZE duplicated in config.py (12 bytes) to avoid circular import with fountain.py
- [06-01]: Profile injection via optional constructor param (profile=None defaults to DEFAULT_PROFILE)
- [06-04]: Checkerboard uses only black (0,0,0) and white (255,255,255) for chroma subsampling robustness
- [06-04]: Perfect capture returns 60.0 dB SNR (capped when noise < 1e-6)
- [06-04]: Benchmark runs encode/sample/decode in-memory (no display or capture hardware needed)

### Pending Todos

None.

### Blockers/Concerns

- Pre-existing test failure in test_xor_ops.py::test_fountain_decoder_with_numba (not introduced by Phase 5).

## Session Continuity

Last session: 2026-02-17T09:02:14Z
Stopped at: Completed 06-04-PLAN.md (Calibration and Benchmark CLI) -- ALL PHASES COMPLETE
Resume file: None
