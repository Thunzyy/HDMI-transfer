# HDMI Exfil

Transfer files over HDMI video signals. The sender encodes arbitrary data into video frames displayed on screen; the receiver captures the feed via an Elgato capture card and decodes the original file. Zero traces on the source machine -- no disk writes, no network activity.

Two sender modes:
- **Browser sender** (`sender.html`) -- zero install on source, open in browser, go fullscreen
- **Python CLI** (`hdmi-send`) -- maximum performance, both protocols

## Hardware Requirements

| Component | Details |
|-----------|---------|
| **Sender PC** | Any PC with HDMI output |
| **Receiver PC** | Elgato 4K X capture card (or compatible USB capture card) |
| **HDMI cable** | Sender GPU output -> capture card input on receiver |

The Elgato 4K X supports 1080p@240fps and 4K@30fps capture.

## Installation

Requires **Python >= 3.11**.

```bash
git clone git@github.com:Thunzyy/HDMI_exfil.git
cd HDMI_exfil
pip install -e ".[dev]"
```

This installs all runtime dependencies (numpy, opencv-python-headless, pygame-ce, numba, screeninfo) and dev tools (pytest, hypothesis).

## Quick Start

### 1. Start the receiver first

```bash
hdmi-recv 0
```

Where `0` is your capture card index (try 0, 1, 2... to find it). A debug window shows the captured feed with a grid overlay.

### 2. Send a file

**Python sender** (best performance):

```bash
hdmi-send secret.zip --mode fountain
```

**Browser sender** (zero install on source):

1. Open `sender.html` in a browser on the source machine
2. Press F11 for fullscreen
3. Select a file and click Start

### 3. Receive

The receiver auto-detects the protocol, shows progress with speed and ETA, and saves the file to `received_files/` with SHA-256 verification.

## Resolution Profiles

Profiles auto-configure all encoding parameters:

| Profile | Resolution | FPS | Throughput | Use Case |
|---------|-----------|-----|-----------|----------|
| `speed` (default) | 1920x1080 | 240 | ~2.8 MB/s | Maximum throughput |
| `balanced` | 1920x1080 | 60 | ~0.7 MB/s | Stable reliability |
| `quality` | 3840x2160 | 30 | ~1.4 MB/s | Best signal margin |

```bash
hdmi-send file.zip --profile quality --mode sequential
hdmi-recv 0 --profile quality
```

## Protocols

### Sequential

Ordered frames with START/DATA/END lifecycle. Reliable over stable connections.

```bash
hdmi-send file.zip --mode sequential --redundancy 3
hdmi-recv 0 --mode sequential
```

### Fountain (LT Codes)

Rateless erasure coding. Sender emits infinite XOR-combined droplets; receiver collects until all chunks are recovered. No back-channel needed -- perfect for one-way HDMI.

```bash
hdmi-send file.zip --mode fountain --fountain-redundancy 1.05
hdmi-recv 0 --mode fountain
```

## CLI Reference

### hdmi-send

```
hdmi-send <input_path> [OPTIONS]

Options:
  --mode {sequential,fountain}   Encoding protocol (default: sequential)
  --profile {speed,balanced,quality}  Resolution profile
  --renderer {pygame,cv2}        Display backend (default: pygame)
  --fps INT                      Target FPS (overrides profile)
  --redundancy INT               Frame repeat count, sequential only (default: 1)
  --fountain-redundancy FLOAT    Stop after K*N droplets (e.g. 1.05 = 5% overhead)
  --screen INT                   Monitor index (default: 0)
```

### hdmi-recv

```
hdmi-recv <source> [OPTIONS]

Arguments:
  source                         Camera index (0, 1, 2...) or video file path

Options:
  --mode {auto,sequential,fountain}  Protocol (default: auto-detect)
  --profile {speed,balanced,quality}  Must match sender's profile
  --output DIR                   Save directory (default: received_files)
  --threaded / --no-threaded     Threaded capture with ring buffer (default: on)
  --buffer-size INT              Ring buffer frames (default: 16)
```

### hdmi-calibrate

Test signal quality before transfers.

```
hdmi-calibrate send                    # Display test pattern
hdmi-calibrate recv <source>           # Analyze captured pattern
hdmi-calibrate loopback <source>       # Both (same machine with Elgato)

Options:
  --profile {speed,balanced,quality}
  --renderer {cv2,pygame}              # send mode only
  --frames INT                         # recv/loopback: frames to average (default: 10)
```

Output includes alignment offset, SNR in dB, and signal quality rating (EXCELLENT/GOOD/FAIR/POOR).

### hdmi-bench

In-memory throughput benchmark (no hardware needed).

```
hdmi-bench [OPTIONS]

Options:
  --profile {speed,balanced,quality}   Default: speed
  --mode {sequential,fountain}         Default: fountain
  --size INT                           Payload size in KB (default: 100)
  --duration FLOAT                     Max seconds for fountain (default: 10)
  --no-json                            Human-readable output
```

Outputs JSON with frames/sec, bytes/sec, overhead %, error rate.

## Encoding

Each 8x8 pixel block encodes **3 bits** (1 bit per RGB channel). Black channel = 0, white channel = 255. A 1920x1080 frame has 240x135 = 32,400 blocks = 97,200 bits = **12,150 bytes** per frame.

Frame headers consume 17 bytes (sequential) or 12 bytes (fountain), leaving 12,133 or 12,138 bytes of payload per frame.

## Architecture

```
src/hdmi_exfil/
  config.py            Constants, ResolutionProfile, PROFILES
  constants.json       Shared source of truth (Python + JS)
  prng.py              SplitMix32 PRNG (cross-language deterministic)
  protocols/
    base.py            EncodingProtocol ABC
    sequential.py      Sequential protocol (START/DATA/END)
    fountain.py        Fountain LT codes + FountainDecoder
    degree.py          Robust Soliton Distribution
  capture/
    source.py          CaptureSource (V4L2/DirectShow/AVFoundation)
    threaded.py        ThreadedCapture with ring buffer
    sampler.py         Frame -> block grid sampling
  display/
    renderer.py        FrameRenderer (cv2), PygameRenderer (SDL2)
    test_patterns.py   Calibration patterns + SNR analysis
    monitors.py        Multi-monitor detection
  file_handling/
    reader.py          File/directory reader (auto-zip)
    writer.py          Output file writer
    metadata.py        Filename, size, SHA-256 embedding
    integrity.py       SHA-256 verification
  cli/
    send.py            hdmi-send entry point
    receive.py         hdmi-recv entry point
    calibrate.py       hdmi-calibrate entry point
    benchmark.py       hdmi-bench entry point
    progress.py        ProgressTracker (speed, ETA)

sender.html            Browser-based fountain sender (zero install)
```

## Troubleshooting

**Receiver shows no data:** Check capture card index (try different numbers). Run `hdmi-calibrate recv 0` to verify signal quality.

**Corrupted transfers:** Lower FPS (`--fps 30`), use `--profile quality`, increase `--redundancy`, or switch to fountain mode which handles frame loss gracefully.

**Capture card not detected:** Ensure the Elgato drivers are installed. On Linux, check that `/dev/video*` devices exist.

**Low FPS:** Use `--renderer pygame` (default) for SDL2 vsync. The cv2 backend caps at ~80fps. Ensure no other apps compete for GPU.

## License

This project is for educational and authorized security research purposes only.
