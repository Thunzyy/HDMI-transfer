# Project Research Summary

**Project:** HDMI Data Exfiltration Tool
**Domain:** Covert data-over-video channel via HDMI capture card
**Researched:** 2026-02-16
**Confidence:** MEDIUM-HIGH

## Executive Summary

This is an HDMI data exfiltration tool that encodes files as visual pixel patterns, transmits them via HDMI signal, and decodes them from a capture card on the receiving side. Expert implementations use fountain codes (rateless erasure codes) for reliability over one-way channels, binary pixel encoding to survive capture card compression artifacts, and high-framerate displays (1080p@240fps) to maximize throughput. The reference implementation TGXf achieved 12.1 Mbps using 3 bits per 8x8 block at lower framerates.

The recommended approach is to refactor the existing working prototype incrementally while preserving its functional core. **The prototype already works through real hardware** — the critical success factor is maintaining that functionality while adding architectural structure, integrity verification, and performance optimization. Use Python with NumPy for encode/decode, pygame-ce for high-speed display (replacing cv2.imshow), OpenCV for cross-platform capture, and Numba JIT for fountain code acceleration. The current fountain implementation uses a custom LT code variant that must remain compatible with the browser sender.

Key risks: (1) Chroma subsampling in capture cards destroys multi-bit color encoding — only binary (0/255) per channel survives reliably, (2) Refactoring breaks the working prototype without proper test gates, (3) Python/JavaScript PRNG must remain perfectly synchronized or fountain decoding produces garbage. Mitigation: Default to 1-bit luma-only encoding for reliability; add loopback tests before any refactoring; create cross-language PRNG test vectors as first validation step.

## Key Findings

### Recommended Stack

The current Python 3.13 + OpenCV + NumPy stack is fundamentally sound. Key upgrades: replace cv2.imshow (debugging tool, caps at ~60-80 FPS) with pygame-ce SDL2 rendering for true high-speed display. Replace Python XOR loops in fountain decoder with Numba JIT compilation (100-1000x speedup). Use opencv-python-headless to avoid GUI conflicts. Cross-platform capture requires backend selection: CAP_V4L2 (Linux), CAP_DSHOW (Windows), CAP_AVFOUNDATION (macOS).

**Core technologies:**
- **Python 3.13 + NumPy 2.4+**: Vectorized bit operations already optimal for encode/decode — np.packbits/unpackbits for binary encoding, np.bitwise_xor for fountain operations
- **pygame-ce**: SDL2-backed hardware-accelerated display via surfarray.blit_array, replaces cv2.imshow to unlock 240fps rendering
- **Numba 0.61+**: JIT-compile fountain code XOR loops with @njit — transforms O(n) Python loops into SIMD machine code, critical for real-time decode
- **OpenCV 4.10+ (headless)**: Cross-platform capture card access via V4L2/DirectShow/AVFoundation backends, MJPEG fourcc for bandwidth efficiency at 240fps
- **pytest + hypothesis**: Property-based testing for encode/decode round-trips with arbitrary binary data, essential for catching edge cases

**Critical version constraint:** Elgato 4K X at 1080p@240fps uses NV12 (4:2:0 chroma subsampling). Only binary encoding (0/255) per channel survives this compression — intermediate gray levels are destroyed.

### Expected Features

**Must have (table stakes):**
- **Frame synchronization** — Currently missing explicit sync pattern, receiver relies on always-running sender. Add magic byte sequence in frame header to detect data vs idle frames
- **Start/end signaling** — Implement frame types (IDLE, START, DATA, END) so receiver knows when transfer begins/ends and can handle multiple sequential transfers
- **File integrity verification** — Zero verification currently. Add SHA-256 hash in START frame metadata and per-frame CRC32 for corruption detection
- **Metadata protocol** — Extend existing filename metadata to include file size and hash, enabling truncation/corruption detection
- **3-bit encoding for fountain mode** — sender.html uses 1bpp (black/white), sender.py uses 3bpp (RGB binary). Upgrade fountain path to 3bpp for 3x throughput
- **Cross-platform receiver** — Remove Windows-only cv2.CAP_DSHOW hardcode, detect platform and use appropriate backend

**Should have (competitive differentiators):**
- **Threaded capture pipeline** — OpenCV's blocking .read() caps at 30-60fps even with 240fps hardware. Dedicated capture thread with ring buffer is mandatory for actual 240fps
- **Calibration mode** — Sender displays known pattern, receiver analyzes to detect alignment offset, measure SNR, determine optimal block size, verify actual capture FPS
- **Robust Soliton Distribution** — Current ad-hoc degree distribution causes 14-42% overhead for small K vs 3-5% with proper distribution. Critical for predictable performance
- **Resolution profiles** — Pre-tested configurations (1080p@240fps "speed", 1080p@60fps "balanced", 4K@30fps "quality") rather than forcing users to calculate parameters
- **Python fountain sender** — Currently only sender.html does fountain encoding. Python sender with fountain + 3bpp = max throughput path

**Defer (v2+):**
- **Multi-level encoding (4+ bits/channel)** — Theoretically doubles throughput but capture card compression destroys intermediate gray levels. Stick with binary (0/255) until proven necessary
- **Encryption** — Physical air-gap means encryption should be applied to file before feeding to sender, not built into transport protocol
- **Raptor codes** — Superior to LT codes (0.2% vs 5% overhead) but significantly more complex and possible patent concerns. LT with proper distribution is sufficient

### Architecture Approach

The prototype is a flat file structure with sequential and fountain protocols sharing only constants. Refactor to src-layout package with protocol abstraction layer, cross-platform platform abstractions, and strict component boundaries. Key pattern: EncodingProtocol ABC defines encode_frame/decode_frame interface, sequential and fountain protocols implement as strategies. All constants move to single constants.json source of truth shared between Python and JavaScript (build step injects into sender.html).

**Major components:**
1. **config.py + constants.json** — Single source of truth for all encoding parameters, resolution profiles, shared between Python and JavaScript via build-time injection
2. **protocols/{sequential,fountain}.py** — Protocol strategy implementations inheriting from EncodingProtocol ABC, contains encode/decode logic with no hardware/file I/O coupling
3. **capture/source.py + sampler.py** — Cross-platform capture card abstraction with backend selection, block sampling separated from protocol logic
4. **display/renderer.py** — Display abstraction (initially pygame-ce SDL2), separated from encoding to enable testing with mock display
5. **file_handling/{reader,writer,metadata}.py** — File I/O and metadata wrapping, shared by both sender and receiver without duplicating logic

**Critical architectural constraint:** Data flow is strictly unidirectional (file → encode → display → HDMI → capture → decode → file) matching the physical one-way channel. No component communicates backward.

### Critical Pitfalls

1. **Chroma subsampling destroys color data** — Elgato 4K X uses NV12 (4:2:0) at 240fps, MJPEG at lower rates. Both compress chroma channels. Only binary encoding (0/255) per channel survives. Current sender.py's 3-bit RGB works because it uses extremes (0 and 255), but receiver_fountain.py correctly reads only green channel (closest to luma). Prevention: Default to luma-only (black/white) as primary mode, treat multi-bit as experimental requiring validation.

2. **PRNG synchronization failure** — JavaScript (sender.html) and Python (receiver_fountain.py) implement same SplitMix32 PRNG but integer semantics differ. JS uses Math.imul + |0 for 32-bit; Python uses & 0xFFFFFFFF. Current Python code has meaningless `(self.a | 0)` copied from JS that does nothing. A single bit difference cascades into completely wrong chunk selection. Prevention: Create test vector file (1000 outputs from seeds [1,2,3,...] in JS), verify Python produces identical sequence.

3. **cv2.waitKey cannot achieve >80 FPS** — sender.py uses cv2.waitKey(delay) for timing but waitKey has ~12-15ms floor regardless of delay parameter, capping display at ~75-80 FPS. The --fps 240 default is physically unachievable with cv2.imshow. Prevention: Replace cv2.imshow with pygame-ce SDL2 or use browser sender (requestAnimationFrame, monitor-limited).

4. **Refactoring breaks working prototype** — System currently works end-to-end through hardware. "Big rewrite" risk is high because hardware is hard to mock and timing-sensitive. Prevention: Add loopback tests to existing code FIRST, then refactor incrementally with test gates after each change. Git tag v0.1-working-prototype before starting.

5. **Encoding mismatch between modes** — sender.py (3-bit, 12-byte header) and sender.html (1-bit, 6-byte header) use incompatible frame formats with no version marker. Pairing wrong sender/receiver produces silent garbage. Prevention: Add magic number (e.g., 0xDA7A for sequential, 0xF0C0 for fountain) as first bytes of every frame header, reject unrecognized frames.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 0: Test Foundation (Prerequisite)
**Rationale:** Existing test_loopback.py is broken (wrong function signatures). Cannot safely refactor without tests. This must be first.
**Delivers:** Working loopback tests for both sequential and fountain modes, baseline functionality verified, git tag v0.1-working-prototype
**Addresses:** Pitfall 4 (refactoring breaks prototype), Pitfall 11 (broken test)
**Avoids:** Starting refactor without safety net
**Research flag:** No research needed — this is code hygiene

### Phase 1: Protocol Foundation
**Rationale:** Frame synchronization and integrity verification are prerequisites for everything else. Without magic numbers and checksums, protocol changes risk silent corruption. Dependencies from FEATURES.md show sync is root of dependency tree.
**Delivers:** Frame header with magic number + version field, START/DATA/END frame types, per-frame CRC32, metadata with SHA-256 hash, cross-platform capture backend selection
**Addresses:** TS-1 (sync), TS-2 (start/end), TS-3 (integrity), TS-4 (metadata), TS-8 (cross-platform), D-5 (per-frame CRC)
**Avoids:** Pitfall 3 (encoding mismatch), Pitfall 7 (Windows-only APIs), Pitfall 9 (no checksums)
**Research flag:** Standard protocol design patterns — skip research-phase

### Phase 2: Architecture Refactor
**Rationale:** With tests and protocol foundation in place, can safely restructure code. Must happen before performance optimization because threaded capture and display changes require clean component boundaries.
**Delivers:** src-layout package, protocol ABC with sequential/fountain implementations, constants.json single source of truth, separated capture/display/file_handling modules, build script for sender.html generation
**Uses:** Python 3.13, NumPy, pytest structure from STACK.md
**Implements:** Protocol strategy pattern, config abstraction, component boundaries from ARCHITECTURE.md
**Addresses:** TS-6 (3-bit fountain), D-9 (Python fountain sender)
**Avoids:** Pitfall 10 (big rewrite), Pitfall 12 (duplicated constants), Pitfall 1 (anti-pattern god module)
**Research flag:** No deep research needed — standard Python packaging patterns

### Phase 3: Performance Optimization
**Rationale:** With clean architecture, can now optimize hotspots: Numba JIT for fountain XOR, pygame-ce for display, threaded capture pipeline. These changes touch multiple components so architecture must be stable first.
**Delivers:** Numba-accelerated fountain encoder/decoder, pygame-ce SDL2 display replacing cv2.imshow, threaded capture with ring buffer, actual FPS measurement and reporting
**Uses:** Numba @njit, pygame-ce, threading patterns from STACK.md
**Addresses:** D-3 (threaded capture), Pitfall 14 (XOR performance), Pitfall 5 (waitKey FPS ceiling), Pitfall 13 (FPS mismatch)
**Avoids:** Premature optimization before architecture is stable
**Research flag:** Minor — pygame-ce API surface area is small, threaded capture is standard pattern

### Phase 4: Fountain Code Optimization
**Rationale:** Now that performance infrastructure is in place, can optimize the fountain code math. This depends on Numba being integrated (Phase 3) and requires empirical testing at different K values.
**Delivers:** Robust Soliton Distribution replacing ad-hoc distribution, Gaussian elimination fallback for small K, configurable redundancy parameter, overhead reduction from ~30% to ~5%
**Addresses:** TS-7 (Robust Soliton), D-6 (fountain optimization), Pitfall 8 (degree distribution)
**Avoids:** Optimizing fountain codes before infrastructure can measure the improvement
**Research flag:** YES — Robust Soliton parameter tuning (c, delta) requires domain research and empirical validation for target K range

### Phase 5: User Experience Polish
**Rationale:** With core functionality stable and performant, add features that make the tool usable without deep technical knowledge.
**Delivers:** Resolution profiles (1080p@240, 1080p@60, 4K@30), calibration mode with auto-parameter detection, benchmarking mode with JSON output, rich progress reporting
**Addresses:** TS-5 (progress reporting), D-1 (profiles), D-4 (calibration), D-8 (benchmarking), D-2 (adaptive block size)
**Avoids:** Building UX before core is stable
**Research flag:** YES — Calibration mode alignment detection needs computer vision research (template matching, corner detection)

### Phase Ordering Rationale

- **Phase 0 first:** Cannot refactor safely without tests. Existing test is broken, must fix immediately.
- **Phase 1 before architecture:** Protocol changes cascade through all code. Better to have correct protocol before restructuring than to restructure twice.
- **Phase 2 before performance:** Clean component boundaries required for threaded capture (separate capture/decode), display replacement (swap out renderer), and Numba integration (protocol hot loops isolated).
- **Phase 3 before fountain optimization:** Need actual FPS measurement and Numba infrastructure before tuning fountain parameters (must measure overhead improvement).
- **Phase 4 empirical:** Robust Soliton needs testing at many K values. Can only do this with fast infrastructure (Phase 3) and proper measurement (Phase 3).
- **Phase 5 last:** UX polish depends on stable core. Calibration auto-tunes parameters that must exist first.

**Dependency chain:** Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 (strict sequence, each builds on previous)

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (Fountain Optimization):** Robust Soliton Distribution parameter selection — theory is clear but optimal c/delta for K=1-1000 range requires literature review and empirical tuning
- **Phase 5 (Calibration Mode):** Alignment detection and auto-parameter tuning — needs computer vision techniques research (template matching, Hough transform, corner detection)

Phases with standard patterns (skip research-phase):
- **Phase 0:** Fixing existing tests, no new patterns
- **Phase 1:** Frame header design, CRC checksums — standard protocol patterns
- **Phase 2:** Python packaging, ABC strategy pattern — well-documented
- **Phase 3:** Threading, Numba JIT basics, pygame-ce API — all documented in respective tool docs

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Core technologies verified from official docs. Numba/pygame-ce recommendations based on performance characteristics and active maintenance. OpenCV capture backends confirmed for all platforms. |
| Features | HIGH | Table stakes derived from codebase gaps (no checksums, no sync) and reference implementation TGXf. Differentiators validated against fountain code literature. Priority ordering matches dependency analysis. |
| Architecture | HIGH | Patterns extracted directly from codebase analysis plus standard Python packaging practices from PyPA. Component boundaries informed by actual coupling problems in prototype. |
| Pitfalls | MEDIUM-HIGH | Critical pitfalls (chroma subsampling, PRNG sync, waitKey FPS ceiling) verified from multiple sources including Elgato specs, OpenCV issue tracker, and independent research. Some hardware-specific pitfalls need validation with actual Elgato 4K X. |

**Overall confidence:** MEDIUM-HIGH

Research is comprehensive and actionable. Stack recommendations are implementation-ready. Feature priorities have clear rationale. Architecture patterns are proven. Pitfalls are specific with concrete prevention strategies.

**Caveat:** Some hardware-specific behaviors (exact chroma subsampling at 240fps, MJPEG quality settings, actual achievable FPS with V4L2 backend) require validation with target capture card during implementation. Research provides expected behavior and mitigation strategies.

### Gaps to Address

- **Actual Elgato 4K X capture at 240fps:** Research indicates NV12 format with 4:2:0 subsampling, but exact behavior needs empirical testing. May discover additional compression or processing in the USB pipeline. Mitigation: Phase 1 includes hardware validation checkpoint, fallback to 1080p@120fps if 240fps proves unreliable.

- **Robust Soliton parameter tuning:** Theory specifies c ∈ [0.1, 0.3] and delta ∈ [0.01, 0.1], but optimal values for K=1-1000 range need empirical testing with actual file transfers. Literature focuses on large K (>10000). Mitigation: Phase 4 includes parameter sweep and benchmarking, document findings.

- **pygame-ce vs cv2.imshow actual performance delta:** Stack research indicates pygame-ce should unlock higher FPS, but exact improvement depends on GPU drivers, SDL2 backend configuration, and OS. Mitigation: Phase 3 includes FPS measurement before/after migration, fallback to cv2.imshow if pygame-ce introduces new issues.

- **Cross-language PRNG verification:** Python implementation appears to have bug (meaningless |0 operator) copied from JavaScript. Exact output divergence unknown until test vectors created. Mitigation: Phase 1 includes PRNG test vector generation and validation as first task, fix before any fountain transfers.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** — All 6 source files analyzed directly: sender.py, receiver.py, receiver_fountain.py, sender.html, common.py, utils.py
- **STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md** — Four parallel research outputs synthesized in this document
- [Elgato 4K X Technical Specifications](https://help.elgato.com/hc/en-us/articles/23658118721421) — 1080p@240fps NV12 capture confirmed
- [OpenCV VideoCapture Documentation](https://docs.opencv.org/3.4/d0/da7/videoio_overview.html) — Backend selection API
- [NumPy 2.4 Release Notes](https://numpy.org/doc/stable/release/2.4.0-notes.html) — bitwise_xor, packbits performance
- [pygame-ce 2.5 Documentation](https://pyga.me/) — surfarray.blit_array API
- [Numba 0.61 Documentation](https://numba.readthedocs.io/en/stable/user/performance-tips.html) — @njit JIT compilation

### Secondary (MEDIUM confidence)
- [ThruGlassXfer (TGXf)](http://thruglassxfer.com/) — 12.1 Mbps reference implementation, validated 3bpp approach
- [Fountain Codes - CMU Course Notes](https://www.andrew.cmu.edu/user/gaurij/FountainCodes.pdf) — Robust Soliton Distribution theory
- [LT Codes - Luby](https://www.inference.org.uk/mackay/dfountain/LT.pdf) — Original LT code paper, overhead analysis
- [PyImageSearch: Threaded OpenCV Capture](https://pyimagesearch.com/2015/12/21/increasing-webcam-fps-with-python-and-opencv/) — 379% improvement with threading
- [Pen Test Partners: Pixel Exfiltration](https://www.pentestpartners.com/security-blog/exfiltration-by-encoding-data-in-pixel-colour-values/) — Binary encoding through capture card compression validated

### Tertiary (LOW confidence)
- [OpenCV Issue #23456](https://github.com/opencv/opencv/issues/23456) — cv2.waitKey timing floor, community reports vary by platform
- [Stream Guides: Elgato 4K X Review](https://streamguides.gg/2024/02/elgato-4k-x-4k-pro-review/) — "RGB mode not true RGB" claim, single source

---
*Research completed: 2026-02-16*
*Ready for roadmap: yes*
