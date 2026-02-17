# Hardware Setup Guide

## Equipment

| Item | Recommended | Notes |
|------|------------|-------|
| Capture card | Elgato 4K X | 1080p@240fps or 4K@30fps capture |
| HDMI cable | Any standard HDMI 2.0 | Supports 4K@60Hz passthrough |
| Sender PC | Any PC with HDMI output | GPU output directly to capture card |
| Receiver PC | Any PC with USB 3.0 | Runs the Python receiver |

Generic USB capture cards also work but may have lower FPS or quality.

## Physical Setup

### Two-PC Setup (production)

```
[Sender PC] --HDMI--> [Elgato 4K X] --USB3--> [Receiver PC]
```

1. Connect HDMI cable from sender's GPU output to the Elgato input
2. Connect the Elgato USB-C to the receiver PC
3. No drivers needed on the sender -- it just outputs video
4. Install Elgato drivers on the receiver (Linux: usually auto-detected as V4L2)

### Loopback Setup (testing on one PC)

```
[GPU HDMI Out] --HDMI--> [Elgato 4K X] --USB3--> [Same PC]
```

Use a second monitor output or a dedicated HDMI port. The sender displays on the HDMI output connected to the Elgato, while you control the receiver from another display.

## Finding Your Capture Card Index

The receiver needs the camera index of your capture card. Try:

```bash
# Try indices 0, 1, 2...
hdmi-recv 0
hdmi-recv 1
hdmi-recv 2
```

On Linux, list video devices:

```bash
ls /dev/video*
v4l2-ctl --list-devices
```

The Elgato typically appears as `/dev/video0` or `/dev/video2`.

## Signal Calibration

Before your first transfer, verify signal quality:

### Step 1: Display test pattern

On the sender PC:

```bash
hdmi-calibrate send --profile speed
```

This shows a black/white checkerboard pattern. Leave it running.

### Step 2: Analyze the captured signal

On the receiver PC:

```bash
hdmi-calibrate recv 0 --profile speed
```

This captures frames, computes alignment and SNR, and reports:

```
Calibration Results:
  Alignment offset: (0, 0) pixels
  SNR: 35.2 dB
  Signal quality: EXCELLENT
  Recommended: block_size=8 is optimal for this setup
```

### Interpreting Results

| SNR | Quality | Action |
|-----|---------|--------|
| > 30 dB | EXCELLENT | Ready for high-speed transfer |
| 20-30 dB | GOOD | Works fine at default settings |
| 10-20 dB | FAIR | Lower FPS or use `--profile quality` |
| < 10 dB | POOR | Check cable, card settings, interference |

### Loopback calibration (same machine)

```bash
hdmi-calibrate loopback 0 --profile speed
```

Displays the pattern, waits 2 seconds for stabilization, captures, and analyzes automatically.

## Elgato Configuration

### Resolution and FPS

The Elgato 4K X supports multiple capture modes. Match the profile you use:

| Profile | Set Elgato to | Expected capture |
|---------|--------------|-----------------|
| `speed` | 1080p, highest FPS | 240fps (1080p) |
| `balanced` | 1080p, 60fps | 60fps |
| `quality` | 4K (3840x2160) | 30fps |

### Linux (V4L2)

Set capture resolution:

```bash
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1920,height=1080
v4l2-ctl -d /dev/video0 --set-parm=240
```

Check current settings:

```bash
v4l2-ctl -d /dev/video0 --get-fmt-video
v4l2-ctl -d /dev/video0 --get-parm
```

### Windows

Use Elgato 4K Capture Utility or OBS to verify the card is detected. The Python receiver accesses it via DirectShow (OpenCV backend).

### macOS

The Elgato is accessed via AVFoundation. OpenCV auto-detects it.

## Running a Transfer

### Sequential mode (ordered, simple)

**Receiver:**
```bash
hdmi-recv 0 --mode sequential --profile speed
```

**Sender:**
```bash
hdmi-send secret.zip --mode sequential --profile speed
```

The sender displays a calibration frame first. Press any key to start. Progress shows frames sent and throughput.

### Fountain mode (resilient, recommended)

**Receiver:**
```bash
hdmi-recv 0 --mode fountain --profile speed
```

**Sender:**
```bash
hdmi-send secret.zip --mode fountain --profile speed
```

Fountain mode is recommended because it handles dropped frames gracefully -- the receiver collects enough droplets to recover the file regardless of which specific frames were lost.

### Auto-detect mode

```bash
hdmi-recv 0  # auto-detects sequential or fountain from frame magic numbers
```

## Benchmarking Your Setup

Run an in-memory benchmark to baseline your hardware:

```bash
hdmi-bench --profile speed --mode fountain --size 100
```

Then compare with a real transfer to understand capture card overhead.

## Troubleshooting

**No video captured:** Ensure the Elgato is detected (`ls /dev/video*` on Linux). Try different USB ports (must be USB 3.0).

**Low capture FPS:** Use `--profile speed` with the Elgato set to 1080p. 4K mode limits to 30fps. Ensure `--threaded` is enabled (default).

**CRC errors during transfer:** Lower the FPS (`--fps 60`), use fountain mode which tolerates frame loss, or run calibration to check signal quality.

**Alignment issues:** If calibration shows non-zero alignment offset, the capture card is cropping or scaling. Ensure capture resolution matches the sender output exactly (1920x1080 for speed/balanced profiles).

**SHA-256 mismatch:** The file was corrupted during transfer. Use fountain mode with higher redundancy: `--fountain-redundancy 1.20` (20% extra droplets).
