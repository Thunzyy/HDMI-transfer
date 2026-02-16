# Feature Landscape

**Domain:** HDMI data exfiltration / data-over-video one-way channel
**Researched:** 2026-02-16
**Overall confidence:** MEDIUM-HIGH (informed by existing codebase analysis, TGXf prior art, fountain code literature, and capture card specifications)

## Table Stakes

Features users expect. Missing = transfer fails or is unreliable to the point of being unusable.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **TS-1: Reliable frame synchronization** | Without sync, receiver cannot distinguish data frames from noise/idle/other content. Current prototype has no explicit sync -- relies on always-running sender and receiver detecting valid headers. This breaks on startup, interruption, and multi-transfer sessions. | High | Requires dedicated sync pattern (magic bytes or visual marker) at known position in each frame. TGXf uses a "bounded region" approach; QRT uses `QRT1` magic header. Our approach should embed a magic byte sequence in the first N bytes of each frame. |
| **TS-2: Start/end of transmission signaling** | Receiver needs to know when a transfer begins and ends. Current fountain receiver auto-detects K from first valid frame but has no explicit start signal and no end signal -- it decodes until complete, with no way to handle sender restart or new file. | Medium | Implement distinct frame types: IDLE (black/pattern), START (metadata), DATA (payload), END (completion signal). Similar to QRT's HDR/DAT/END frame types. |
| **TS-3: File integrity verification (checksum)** | One-way channel means no retransmission. Must verify data arrived correctly. Currently zero verification -- fountain decoder produces output with no way to know if it is correct. | Medium | Embed SHA-256 hash of original file in START frame metadata. Receiver computes hash after reassembly and reports PASS/FAIL. CRC32 per-frame is also useful for frame-level validation but SHA-256 for file-level is the standard. |
| **TS-4: Metadata protocol (filename, size, hash)** | Receiver needs to know what it is receiving. Current implementation has basic filename metadata (4-byte length + name bytes) but no file size or hash, making it impossible to detect truncation or corruption. | Low | Extend metadata header: filename (existing), file size (4 bytes), SHA-256 hash (32 bytes), timestamp (optional). Embed in START frame. |
| **TS-5: Progress reporting and transfer statistics** | User has no idea if transfer is working, how fast it is going, or when it will finish. Current receiver prints frame count but no speed, ETA, or completion percentage for fountain mode. | Low | Real-time display: frames received, unique chunks decoded, K total, decode %, estimated speed (bytes/sec), ETA. Update every 0.5-1s. Terminal-based, no GUI needed. |
| **TS-6: Multi-bit per block encoding (3 bits/block)** | Current fountain sender.html uses 1 bit/block (black/white only), while sender.py uses 3 bits/block (1 bit per RGB channel). The fountain path is leaving 3x throughput on the table. This is the single biggest easy win. | Medium | Upgrade sender.html and receiver_fountain.py to use 3 bits/block (R=0/255, G=0/255, B=0/255 per block). TGXf achieved 12.1 Mbps at 3bpp -- validates this approach for HDMI capture. Elgato 4K X supports NV12 and 4:2:2 capture at 1080p240 -- 3bpp binary encoding (0 or 255 per channel) survives chroma subsampling because values are extremes. |
| **TS-7: Robust degree distribution for fountain codes** | Current degree distribution is hand-tuned (10% degree-1, 50% degree-2, 40% random up to 20). This is not based on the Robust Soliton Distribution from literature. For small K (typical: 1-500 chunks for files up to 2MB), overhead can be 14-42% with naive distributions vs 3-5% with proper tuning. | High | Implement Robust Soliton Distribution with parameters c and delta. For small K, combine belief propagation with Gaussian elimination for final decoding. Literature shows this reduces overhead from ~42% to ~3% for K=500. |
| **TS-8: Cross-platform receiver (remove Windows-only deps)** | receiver_fountain.py uses `cv2.CAP_DSHOW` (DirectShow, Windows-only). Receiver should work on Linux and macOS where Elgato cards are also used. | Low | Use platform detection: CAP_DSHOW on Windows, CAP_V4L2 on Linux, CAP_AVFOUNDATION on macOS. Or just omit backend flag and let OpenCV auto-detect. |

## Differentiators

Features that set this tool apart from TGXf, txqr, and naive approaches. Not expected, but create significant value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **D-1: Multi-resolution mode profiles** | Different hardware setups benefit from different settings. 4K@30fps = max data per frame but slow refresh. 1080p@240fps = 8x more frames but less data per frame. 1080p@60fps = middle ground. Provide tested, named profiles ("speed", "balanced", "reliable") rather than forcing users to calculate parameters. | Medium | Profiles: `4k30` (3840x2160, 30fps, ~10MB/frame raw), `1080p240` (1920x1080, 240fps, ~1MB/frame raw), `1080p60` (1920x1080, 60fps, lower CPU demand). Each profile sets: resolution, block size, fps target, fountain code parameters. Benchmark each to find actual throughput. |
| **D-2: Adaptive block size based on capture quality** | Larger blocks (16x16) are more robust to alignment errors and compression artifacts. Smaller blocks (4x4) pack more data. Let the system auto-tune or provide presets. Current 8x8 is a reasonable default but not optimal for all scenarios. | Medium | Provide block sizes 4x4, 8x8, 16x16. Default 8x8. Calibration mode (see D-4) can recommend optimal block size by testing capture fidelity at each size. Smaller blocks = more data but require better alignment. |
| **D-3: Threaded capture pipeline** | At 240fps, OpenCV's blocking `.read()` is the bottleneck -- real-world tests show it caps at ~30-60fps even with 240fps-capable hardware. A dedicated capture thread with frame buffer is essential for high throughput. Literature shows up to 379% improvement with threaded capture. | Medium | Separate capture thread fills a ring buffer. Processing thread pulls latest frame. Measure actual achieved capture FPS and report it. This is not a "nice to have" -- at 240fps target, it is nearly mandatory to actually achieve that rate. |
| **D-4: Calibration mode** | Before transfer, sender displays a known calibration pattern. Receiver analyzes captured pattern to detect: alignment offset (pixel shift), scaling, color accuracy, achievable block size, and capture FPS. Current prototype has a basic calibration frame in sender.py but receiver does not analyze it. | High | Calibration sequence: 1) Sender displays alignment grid with known pattern at corners, 2) Receiver captures and analyzes: detects sub-pixel offset, measures SNR per channel, determines max usable block size, measures actual capture FPS. 3) Results feed into transfer parameters. TGXf uses a "bounded region" approach; we should auto-detect the region. |
| **D-5: Per-frame CRC for frame-level error detection** | Beyond file-level SHA-256, detect per-frame corruption immediately. Allows the receiver to count and report corrupted frames in real time, even during fountain decoding. Useful for diagnostics and tuning. | Low | Add CRC32 (4 bytes) to each frame's header. Receiver validates before processing. Corrupted frames are discarded rather than fed to the decoder. QRT protocol uses this exact approach. |
| **D-6: Fountain code overhead optimization** | Move from custom degree distribution to Robust Soliton Distribution. Add Gaussian elimination as fallback when belief propagation stalls (standard technique for small K). Target: decode at K + 5% overhead instead of K + 30%. | High | Implement proper RSD with tunable c (0.1-0.3) and delta (0.01-0.1). Add Gaussian elimination decoder for the final 5-10% of unchunked symbols. This is well-documented in literature but requires careful implementation. For very small K (<50), even simple random linear coding with GE may outperform LT codes. |
| **D-7: Session management (multi-transfer)** | Current tool handles one transfer per run. Support sending multiple files sequentially without restarting sender/receiver. Each transfer gets a session ID. | Medium | Session ID (random 4-byte value) in every frame header. Receiver detects new session ID = new transfer. Enables continuous operation. |
| **D-8: Benchmarking mode** | Automated throughput measurement. Send known data, measure: actual FPS captured, frame loss rate, decode overhead ratio, effective throughput (bytes/sec). Essential for comparing configurations and publishing results. | Medium | `--benchmark` flag sends random data of configurable size. Receiver reports detailed statistics: capture FPS, unique frames/sec, fountain overhead, raw throughput, effective throughput, time to decode. Outputs machine-parseable results (JSON). |
| **D-9: Python sender with fountain codes** | Currently sender.py uses sequential encoding (3 bits/block) while sender.html uses fountain encoding (1 bit/block). Combine both: Python sender with fountain codes AND 3 bits/block. This is the maximum throughput path. | Medium | Port fountain code logic from sender.html to Python sender. Use numpy for XOR operations. Add 3-bit RGB encoding. Python sender + fountain codes + 3bpp + threaded display = theoretical max throughput. |

## Anti-Features

Features to explicitly NOT build. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **AF-1: Back-channel communication** | The entire value proposition is one-way HDMI channel with zero traces on source. Any back-channel (network, USB, audio) defeats the purpose and adds complexity. Fountain codes exist precisely because there is no back-channel. | Keep the one-way constraint absolute. Fountain codes handle what a back-channel would handle (retransmission). All tuning must be done pre-transfer (calibration) or be adaptive on the sender side only (send excess droplets). |
| **AF-2: Steganography / hiding data in normal video** | Data is encoded as visible pixel blocks, not hidden in normal video content. Steganographic encoding would dramatically reduce throughput (to kbps range) and add massive complexity. The threat model assumes physical control of the capture path, not visual concealment. | Keep visible block encoding. If concealment is needed, it is a fundamentally different tool with different tradeoffs. |
| **AF-3: Encryption** | HDMI is a physical air-gapped channel. Adding encryption adds complexity, computation overhead on the sender (especially browser sender), and solves a problem that does not exist in the threat model. | If encryption is ever needed, it should be applied to the file before feeding it to the sender, not built into the transport protocol. Keep the transport layer simple. |
| **AF-4: GUI application** | CLI + browser is the right interface. A GUI adds massive development overhead, cross-platform headaches, and dependencies. The browser sender IS the GUI for the source PC. The receiver needs terminal output only. | CLI with rich terminal output (progress bars, stats). The browser sender.html already provides the GUI experience on the source machine. |
| **AF-5: Multi-file queue / batch transfers** | Adds session management complexity, partial failure handling, and progress tracking across files. One file at a time is simpler and more reliable. Directory transfer already works via auto-zip. | Keep auto-zip for directories. If multiple files need sending, zip them first or send sequentially. Session management (D-7) enables sequential transfers without restart, which is sufficient. |
| **AF-6: Intermediate grayscale / multi-level encoding (4+ bits per channel)** | Going beyond binary per channel (0 or 255) to intermediate values (0, 85, 170, 255 for 2 bits/channel) is theoretically possible but extremely fragile. Capture cards apply chroma subsampling (4:2:2 or 4:2:0), compression, gamma curves, and noise that destroy intermediate levels. TGXf explicitly found that 1bpp (binary per channel) is the only reliable mode across most capture cards. The Elgato 4K X does NV12 at 240fps which is 4:2:0 -- only the extremes (0 and 255) survive reliably. | Stick with binary encoding: each channel is 0 or 255. This gives 3 bits per block with 3 channels, which is already the practical maximum for capture card channels. If more throughput is needed, reduce block size (more blocks per frame) rather than adding gray levels. |
| **AF-7: Real-time compression on sender** | Compressing data before encoding into frames adds CPU overhead on the source PC and complexity. For the browser sender, JavaScript compression is slow. The file should be pre-compressed if needed. | If files are compressible, compress before feeding to sender. The transport protocol should treat data as opaque bytes. Auto-zip for directories is acceptable because it is a one-time pre-processing step, not per-frame. |
| **AF-8: Audio channel data encoding** | HDMI carries audio alongside video. Some approaches try to encode data in the audio channel for additional bandwidth. This adds complexity, requires audio capture setup, and the throughput gain is negligible compared to video (audio is ~1.5 Mbps vs video at ~250 MB/s raw). | Ignore audio channel entirely. Video bandwidth dwarfs audio. |
| **AF-9: Raptor/RaptorQ codes** | While Raptor codes are theoretically superior to LT codes (O(K) vs O(K log K), ~0.2% overhead vs ~5%), they are significantly more complex to implement, may have patent concerns (Qualcomm), and the practical improvement for our use case (K < 1000 typically) is modest. LT codes with Robust Soliton + Gaussian elimination get close enough. | Use LT codes with Robust Soliton Distribution and Gaussian elimination fallback. This gets overhead to ~3-5% for typical K values, which is sufficient. Revisit Raptor only if LT overhead is demonstrably the bottleneck (unlikely -- capture FPS will be the bottleneck). |

## Feature Dependencies

```
TS-1 (Frame sync)
  |
  +---> TS-2 (Start/end signaling) -- requires frame type field in sync header
  |       |
  |       +---> TS-3 (Integrity verification) -- hash in START frame
  |       |
  |       +---> TS-4 (Metadata protocol) -- metadata in START frame
  |       |
  |       +---> D-7 (Session management) -- session ID in frame header
  |
  +---> D-5 (Per-frame CRC) -- CRC in frame header alongside sync

TS-6 (3-bit encoding)
  |
  +---> D-9 (Python fountain sender) -- combines fountain + 3bpp
  |
  +---> D-1 (Multi-resolution profiles) -- each profile sets bpp mode

TS-7 (Robust Soliton Distribution)
  |
  +---> D-6 (Fountain optimization + GE) -- builds on proper distribution

D-3 (Threaded capture)
  |
  +---> D-4 (Calibration mode) -- needs fast capture to measure FPS
  |
  +---> D-8 (Benchmarking) -- needs accurate FPS measurement

TS-8 (Cross-platform) -- independent, can be done anytime

TS-5 (Progress reporting) -- independent, can be done anytime

D-2 (Adaptive block size) -- depends on D-4 (calibration) for auto-selection
```

## Priority Recommendation

For the next milestone, prioritize in this order:

### Phase 1: Foundation (must have for reliable transfers)
1. **TS-1: Frame synchronization** -- everything depends on this
2. **TS-2: Start/end signaling** -- frame protocol enables everything else
3. **TS-6: 3-bit encoding for fountain mode** -- 3x throughput, low risk
4. **TS-5: Progress reporting** -- needed for all testing and benchmarking
5. **TS-8: Cross-platform receiver** -- quick win, unblocks Linux/Mac testing

### Phase 2: Integrity and Performance
6. **TS-4: Metadata protocol** -- extend START frame with size + hash
7. **TS-3: File integrity verification** -- SHA-256 in metadata, verify on completion
8. **D-5: Per-frame CRC** -- frame-level error detection
9. **D-3: Threaded capture pipeline** -- unlock actual high FPS capture
10. **D-9: Python fountain sender** -- max throughput sender path

### Phase 3: Optimization and Polish
11. **TS-7: Robust Soliton Distribution** -- reduce fountain overhead
12. **D-6: Fountain optimization + GE** -- further reduce overhead
13. **D-1: Multi-resolution profiles** -- named presets for different setups
14. **D-4: Calibration mode** -- auto-detect optimal parameters
15. **D-8: Benchmarking mode** -- automated performance measurement

### Defer (post-milestone)
- **D-2: Adaptive block size** -- needs calibration mode first, nice to have
- **D-7: Session management** -- only needed for continuous operation

## Theoretical Throughput Analysis

Understanding the ceiling helps prioritize which features actually move the needle.

### Current state (sender.html fountain mode, 1bpp)
- 1920x1080 resolution, 8x8 blocks = 240 cols x 135 rows = 32,400 blocks
- 1 bit per block = 32,400 bits = 4,050 bytes per frame
- At 60fps capture (realistic with OpenCV blocking reads): 243 KB/s = ~1.9 Mbps
- With fountain overhead (~30% with current distribution): ~1.3 Mbps effective

### After TS-6 (3bpp fountain mode)
- 3 bits per block = 97,200 bits = 12,150 bytes per frame
- At 60fps: 729 KB/s = ~5.8 Mbps
- With fountain overhead (~30%): ~4.1 Mbps effective

### After D-3 + D-6 (threaded capture + optimized fountain)
- At 240fps with threaded capture: 12,150 * 240 = 2.92 MB/s = ~23.3 Mbps
- With optimized fountain overhead (~5%): ~22.1 Mbps effective

### After D-1 (4K@30fps profile, 3bpp)
- 3840x2160, 8x8 blocks = 480 cols x 270 rows = 129,600 blocks
- 3 bits per block = 388,800 bits = 48,600 bytes per frame
- At 30fps: 1.46 MB/s = ~11.7 Mbps
- Note: 1080p@240fps (23 Mbps) likely beats 4K@30fps (11.7 Mbps) -- needs benchmarking

### Theoretical maximum (1080p@240fps, 4x4 blocks, 3bpp)
- 480 cols x 270 rows = 129,600 blocks at 4x4
- 3 bits per block = 388,800 bits = 48,600 bytes per frame
- At 240fps: 11.66 MB/s = ~93.3 Mbps
- This is aggressive -- 4x4 blocks require perfect alignment

### Bottleneck analysis
1. **Capture FPS** (biggest bottleneck): OpenCV blocking reads limit to ~30-60fps. Threaded capture is essential.
2. **Fountain overhead** (second bottleneck): 30% overhead with current distribution wastes ~30% of frames.
3. **Bits per block** (third bottleneck): 1bpp vs 3bpp is a 3x difference.
4. **Block size** (fourth bottleneck): 8x8 vs 4x4 is a 4x difference but requires better alignment.
5. **Frame processing time** (fifth): numpy operations for encode/decode need to be fast.

## Sources

### Direct prior art (HIGH confidence)
- [ThruGlassXfer (TGXf)](http://thruglassxfer.com/) -- closest comparable tool, achieved 12.1 Mbps at 3bpp/10fps via HDMI capture
- [QRT Protocol](https://github.com/smyrgeorge/qrt) -- multi-QR screen-to-camera transfer with CRC32 integrity, HDR/DAT/END frame types
- [TXQR / divan/txqr](https://github.com/divan/txqr) -- animated QR transfer using fountain codes, measured ~25 kbps at 12fps

### Fountain code literature (HIGH confidence)
- [Fountain Codes - CMU](https://www.andrew.cmu.edu/user/gaurij/FountainCodes.pdf) -- Robust Soliton Distribution theory
- [LT Codes - Luby](https://www.inference.org.uk/mackay/dfountain/LT.pdf) -- original LT code paper
- [Raptor Codes - Qualcomm](https://www.qualcomm.com/content/dam/qcomm-martech/dm-assets/documents/Raptor_Codes_IEEE_technical_analysis.pdf) -- Raptor vs LT performance analysis
- [Fountain code - Wikipedia](https://en.wikipedia.org/wiki/Fountain_code) -- practical overhead numbers: LT ~5-14% for K=2000-10000, Raptor ~0.2%
- [Fountain codes blog - divan](https://divan.dev/posts/fountaincodes/) -- practical LT overhead measurement, ~20% frame loss tolerance

### Capture card specifications (MEDIUM confidence -- official docs but 403 on some pages)
- [Elgato 4K X Specifications](https://help.elgato.com/hc/en-us/articles/23658118721421-Elgato-Game-Capture-4K-X-Technical-Specifications) -- 1080p@240fps capture, HDMI 2.1, USB 3.2 Gen 2
- [Elgato 4K X Resolutions](https://help.elgato.com/hc/en-us/articles/23479175821069) -- NV12 at 240fps, YUY2 4:2:2 at lower rates

### OpenCV performance (MEDIUM confidence -- community forums + PyImageSearch)
- [OpenCV VideoCapture FPS](https://forum.opencv.org/t/capture-speed-framerate-of-cv2-videocapture/5665) -- blocking reads limit practical FPS
- [Threaded capture - PyImageSearch](https://pyimagesearch.com/2015/12/21/increasing-webcam-fps-with-python-and-opencv/) -- up to 379% improvement with threading
- [Frame synchronization - Wikipedia](https://en.wikipedia.org/wiki/Frame_synchronization) -- frame alignment signal theory

### File integrity (HIGH confidence -- well-established)
- [File verification - Wikipedia](https://en.wikipedia.org/wiki/File_verification) -- SHA-256 for integrity, CRC32 for error detection
- [FIVER algorithm](https://arxiv.org/pdf/1811.01161) -- overlapping checksum computation with transfer

### Visual channel encoding (MEDIUM confidence -- academic papers)
- [RGB VLC MIMO](https://opg.optica.org/oe/fulltext.cfm?uri=oe-24-9-9383&id=340132) -- multi-bit RGB encoding theory
- [HiLight screen-camera](https://www.cs.columbia.edu/~xia/publication/mobisys15-hilight/mobisys15-hilight.pdf) -- pixel modulation for screen-camera data transfer
- [Color depth - Wikipedia](https://en.wikipedia.org/wiki/Color_depth) -- 8-bit per channel, chroma subsampling effects
