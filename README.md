<p align="center">
  <img src="docs/logo_hdmi_animated.svg" alt="HDMI Transfer — file transfer over HDMI video" width="160" />
</p>

<h1 align="center"> HDMI Transfer</h1>

<p align="center"><strong>File Transfer over HDMI , turn a file into a video signal. Rebuild it on another computer with a capture card.</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&amp;logoColor=white" alt="Python 3.11 or later" />
  <img src="https://img.shields.io/badge/Sender-Standalone_HTML-E34F26?logo=html5&amp;logoColor=white" alt="Standalone HTML sender" />
  <img src="https://img.shields.io/badge/Transport-HDMI-7c8aff" alt="HDMI video transport" />
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#screenshots">Screenshots</a> ·
  <a href="#transfer-speeds">Transfer speeds</a> ·
  <a href="docs/getting-started.md">Installation guide</a> ·
  <a href="docs/hardware-setup.md">Hardware setup</a> ·
  <a href="#faq">FAQ</a>
</p>

**HDMI Transfer** encodes files into video frames displayed through an HDMI output. On the receiving computer, an **HDMI-to-USB capture card** captures those frames so the software can reconstruct the original file. The file payload travels through video; no network file share is required.

A browser-based sender, a USB capture-card receiver, fountain codes and a local Python/Flask web interface work together to move files between two computers.

> **Proof of concept (POC):** this is an experimental project for demonstrating file transfer over HDMI video.

<p align="center">
  <img src="docs/images/receiver.png" alt="HDMI Transfer receiver: capture device selection, Balanced profile, video preview and file progress" width="1100" />
</p>

## How it works

<p align="center">
  <img src="docs/images/how-it-works.svg" alt="Sender PC encodes a file into video frames; an HDMI cable carries the signal to a capture card; USB carries captured video to the receiver PC, which reconstructs the file" width="1200" />
</p>

1. **Choose** a file in the browser sender or through the command line.
2. **Display** the encoded frames full-screen on the HDMI output connected to the capture card.
3. **Receive** through the local interface, then download the reconstructed file.



## Screenshots

| Send | Configure |
| --- | --- |
| [![HDMI Transfer sender with a text file ready to transmit](docs/images/sender.png)](docs/images/sender.png) | [![HDMI Transfer web interface settings](docs/images/settings.png)](docs/images/settings.png) |
| Choose a file, protocol and profile. | Adjust the settings in the local interface. |


## Why HDMI Transfer?

- **Video transport**: move a file between two computers using HDMI and a USB capture card.
- **Standalone sender**: open `sender.html` locally in a browser, with no Python installation on the sending computer.
- **Browser-based reception**: select a capture device, preview the signal, track progress, download files and browse history.
- **Fountain codes**: reconstruct a file from enough packets, even when some video frames are lost.
- **Explicit settings**: choose Balanced, Speed or Quality profiles and configure the encoding.
- **CLI tools**: send, receive, calibrate and benchmark for reproducible experiments.


## Quick start

### Docker


```bash
docker compose up --build -d --wait
```

Open **[http://localhost:5000](http://localhost:5000)**

```bash
docker compose stop    # Stop; keep received files
docker compose start  # Start again
```

### Native installation

### 1. Prepare the receiving computer

Install [Git](https://git-scm.com/downloads) and [uv](https://docs.astral.sh/uv/getting-started/installation/), then open a terminal:

```bash
git clone https://github.com/Thunzyy/HDMI-transfer.git
cd HDMI-transfer
```


### 2. Launch

**Windows — PowerShell or terminal:**

```powershell
.\start.bat
```

**Linux / macOS — shell:**

```bash
sh start.sh
```

The launchers install web dependencies into `.venv`, then start the server. The first launch requires access to dependency downloads. Open **[http://localhost:5000](http://localhost:5000)** and keep the terminal open. Stop the server with `Ctrl+C`.

Windows is the automated quality-gate platform. A POSIX launcher is provided for Linux/macOS; capture-card and driver compatibility must be checked on each system.

<details>
<summary>Manual commands, without a launcher</summary>

```bash
uv sync --locked --extra web
uv run --no-sync hdmi-web
```

</details>

### 3. Transfer your first file

1. Connect **sender PC HDMI output → capture card HDMI input → receiver PC USB port**.
2. Copy [`sender.html`](sender.html) to the sending computer using an authorized method, then open it in a browser. It runs in offline mode by default.
3. On the receiver, open **Receive**, choose the capture card and select **Fountain · Balanced · 2 bpc · Preview Low**.
4. On the sender, choose a small test file and match the receiver’s protocol, profile and encoding settings.
5. Move the sender window to the display connected to the capture card. Click **Start** on the receiver, then **Start transmission** on the sender. The signal must fill the captured display.
6. Once reception is complete, use **Download** on the receiver. Stop the sender if it is still transmitting.

**Need to load the sender over a LAN or test on a single PC?** The [step-by-step guide](docs/getting-started.md) covers both options, display settings and common problems.

## Choose your setup

| Goal | Setup |
| --- | --- |
| Two PCs with no shared network | Local `sender.html` + local web receiver |
| Load the sender from the receiver on a trusted LAN | Start the server with `--host 0.0.0.0`, then open `http://RECEIVER_IP:5000/sender` |
| Test on one PC with an HDMI capture card | `/sender/test` — explicit local test mode |
| Automate sending or receiving | [CLI commands](docs/getting-started.md#command-line-usage) |

LAN mode uses the network to serve the interface. To avoid any network dependency between the two computers, prepare the standalone HTML file in advance. The local server exposes received files: restrict LAN access to a trusted network.

## Profiles

| Profile | Resolution | Target FPS | When to use it |
| --- | --- | ---: | --- |
| **Balanced** | 1920 × 1080 | 60 | Recommended for your first transfer |
| Speed | 1920 × 1080 | 240 | A high-refresh-rate HDMI path and compatible capture card |
| Quality | 3840 × 2160 | 30 | Experiments with a 4K-compatible chain |

Selecting Speed does not turn a 60 Hz capture card into a 240 Hz device. See [calibration and signal checks](docs/hardware-setup.md).

## Transfer speeds

The following are **theoretical encoded-payload ceilings**, not measured file-transfer speeds. They use **Fountain, 2 bits per RGB channel, 8 × 8 pixel blocks**, and assume every frame reaches the receiver at the stated cadence.

| Profile | Resolution / effective FPS assumed | Payload per frame | Theoretical MB/s | Theoretical Mbps |
| --- | --- | ---: | ---: | ---: |
| **Balanced** | 1920 × 1080 / 60 | 24,284 bytes | **1.46** | **11.66** |
| Speed | 1920 × 1080 / 240 | 24,284 bytes | 5.83 | 46.63 |
| Quality | 3840 × 2160 / 30 | 97,184 bytes | 2.92 | 23.32 |

**MB/s = million bytes per second; Mbps = million bits per second (8 bits = 1 byte).**

Calculation: `payload bytes/frame = (width / 8) × (height / 8) × 3 × 2 / 8 − 16`; multiply by effective FPS for bytes/second. The 16-byte Fountain header is deducted. These values follow the [profile definitions](src/interfaces/browser_sender/protocol.generated.js) and [sender calculation](src/interfaces/browser_sender/app.js).

Actual useful-file throughput is lower because of Fountain redundancy, frame loss, calibration, decoding and file reconstruction. The browser caps sending to the detected display refresh rate: **Speed on a 60 Hz path has the same theoretical ceiling as Balanced at 60 FPS**. The capture card and receiver must also keep up. HDMI link bandwidth is not the file-transfer speed.

For a hardware measurement, transfer a known file, verify its SHA-256 result, and divide its size by the receiver's reported transfer duration. Include setup/calibration time separately when measuring total user wait time. Software benchmarks and Docker smoke tests do not measure HDMI throughput; the table above is not a hardware benchmark.

### Compared with Wi-Fi, Bluetooth, Ethernet and USB

**Scale comparison only, not a head-to-head benchmark.** HDMI Transfer values are encoded-payload ceilings after the Fountain header; the other rows are nominal link/signaling rates **before** protocol overhead. The MB/s column is simply Mbps divided by eight, not an achievable file-copy speed. Wi-Fi rows are specific adapter examples, not the maximum of each generation.

| Connection / example configuration | Rate (Mbps) | Equivalent MB/s | What the number represents |
| --- | ---: | ---: | --- |
| Bluetooth Classic, EDR 3 Mb/s mode | 3 | 0.375 | Radio PHY rate, before packet overhead ([Bluetooth SIG](https://www.bluetooth.com/learn-about-bluetooth/tech-overview/)) |
| **HDMI Transfer — Balanced** | **11.66** | **1.46** | POC payload ceiling, 1080p60 / 2 bpc |
| HDMI Transfer — Quality | 23.32 | 2.92 | POC payload ceiling, 4K30 / 2 bpc |
| HDMI Transfer — Speed | 46.63 | 5.83 | POC payload ceiling, 1080p240 / 2 bpc |
| Wi-Fi 6 — Intel AX203, 2×2 | 1,200 | 150 | Adapter maximum link rate ([Intel](https://www.intel.com/content/www/us/en/products/details/wireless/wi-fi-6-series/downloads.html)) |
| USB 3.2 Gen 1 — USB 5Gbps | 5,000 | 625 | Bus signaling rate, before encoding/transfer overhead ([USB-IF](https://www.usb.org/usb-32-0)) |

The POC's calculated capacity sits above the Bluetooth mode shown and well below these Wi-Fi and USB link rates. That does **not** establish real-world speed ratios: radio conditions, protocol overhead, storage and implementation affect actual transfers. A USB drive also needs a write and a read to move a file between PCs; its bus rate is not its flash-storage speed.

HDMI Transfer demonstrates a video-based file channel when a shared network is unavailable. For routine large-file transfers, a working Wi-Fi/Ethernet connection or suitable USB storage is generally a more practical choice. To compare actual performance, use the same file, verify its hash, and measure complete transfer time on each setup. Reference specifications checked on 2026-09-28.

## FAQ

### Can I transfer files with just an HDMI cable between two computers?

The receiving computer needs an HDMI input. Most PC HDMI ports are outputs, so an HDMI-to-USB capture card is required.

### Do I need Internet access or a shared network?

Initial installation downloads dependencies. After setup, the file payload travels over HDMI. A local HTML sender and an already-installed receiver can operate without a shared network.

### Is the transfer encrypted?

Video encoding and fountain codes are not encryption. Encrypt the file before sending it if confidentiality is required.

### What throughput should I expect?

See [Transfer speeds](#transfer-speeds): the recommended Balanced configuration has a theoretical ceiling of **1.46 MB/s (11.66 Mbps)** at 60 FPS. Actual file throughput depends on your hardware and protocol overhead; this POC does not guarantee that speed.

### Why is the preview black, or why does decoding fail?

Check the capture source, close other applications using the card, verify the correct HDMI display and return to **Fountain + Balanced + 2 bpc** on both sides. See [troubleshooting](docs/getting-started.md#troubleshooting).

## Documentation and development

All project documentation is available in English.

| Document | Contents |
| --- | --- |
| [Installation and quick start](docs/getting-started.md) | Prerequisites, two-PC setup, offline mode, LAN, CLI and troubleshooting |
| [Hardware and calibration](docs/hardware-setup.md) | Wiring, displays, capture devices and loopback testing |
| [Architecture](docs/architecture.md) | Code organization and responsibilities |
| [Testing](docs/testing.md) | Quality gate and hardware-testing boundaries |
| [Migration](docs/migration.md) | Source layout and compatibility |
| [Screenshots](docs/images/README.md) | Provenance and reproducible capture |
| [Assistant overview](llms.txt) | Project summary and source links |



## License

Licensed under the [MIT License](LICENSE). Copyright (c) 2026 Thunzyy.
