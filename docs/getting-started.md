# Install and start HDMI Transfer

[Back to the overview](../README.md)

## Docker option

With Docker running, run `docker compose up --build -d --wait`, then open `http://localhost:5000`. No local Python installation is needed. Received files persist in a Docker volume. Physical capture requires access to a capture device inside the container; Docker Desktop does not automatically expose host USB capture cards. For native Linux device mapping, see [hardware setup](hardware-setup.md#docker-on-native-linux).

## Prerequisites

- Receiver PC: Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), the capture-card driver and a suitable USB port.
- Sender PC: a recent browser and an HDMI output. `sender.html` does not require Python.
- Connection: an HDMI cable and an HDMI-to-USB capture card. Two HDMI outputs cannot receive video from each other.
- Python: version 3.11 or later. uv uses `.python-version` and can download Python if needed.

Install uv on Windows:

```powershell
winget install --id=astral-sh.uv -e
```

On macOS with Homebrew:

```bash
brew install uv
```

For Linux and other methods, follow the [official uv instructions](https://docs.astral.sh/uv/getting-started/installation/). Reopen your terminal, then check `uv --version` and `git --version`.

## Repository access

If the repository is private, sign in with an authorized account through Git Credential Manager or GitHub CLI:

```bash
gh auth login
gh repo clone Thunzyy/HDMI-transfer
cd HDMI-transfer
```

With Git authentication already configured:

```bash
git clone https://github.com/Thunzyy/HDMI-transfer.git
cd HDMI-transfer
```

You can also use **Code → Download ZIP** on GitHub. Extract the entire folder and open a terminal there.

## Install and launch the receiver

On Windows:

```powershell
.\start.bat
```

On Linux/macOS:

```bash
sh start.sh
```

Or run the commands directly:

```bash
uv sync --locked --extra web
uv run --no-sync hdmi-web
```

Open [http://localhost:5000](http://localhost:5000). The launchers run from the project directory, synchronize `.venv` with `uv.lock`, and forward arguments to the server. They stop if installation fails. The first launch may download Python and dependencies; later launches reuse the environment.

The server listens on `127.0.0.1` by default. Received files are stored in `received_files/` relative to the launch directory. Keep the terminal open; press `Ctrl+C` to stop the server.

To change the port:

```powershell
.\start.bat --port 5001
```

On POSIX systems, use `sh start.sh --port 5001`, then open `http://localhost:5001`.

## Two PCs without a shared network

```text
Sender PC                   Capture card                 Receiver PC
sender.html → HDMI output → HDMI input → USB output → Receive interface
```

1. Install the receiver and copy `sender.html` to the sender PC in advance using an authorized method.
2. Connect the card and its USB cable. Use the driver and USB port required by the manufacturer.
3. In the sender PC's display settings, identify the output connected to the card. Start at 1920 × 1080 and 60 Hz.
4. Open `sender.html` locally, select a small test file and move the browser window to that output. The default mode is **2-PC offline sender**, with no receiver API.
5. Select the card in **Receive**. Use **Fountain**, **Balanced** and **2 bpc** on both interfaces. Keep **Preview quality: Low** on the receiver.
6. Click **Start** on the receiver, then **Start transmission** on the sender. Allow full-screen mode if prompted. Nothing should cover the signal shown to the capture card.
7. Wait for **Download**, save the file and stop transmission. Compare SHA-256 hashes of the original and downloaded files to validate the hardware path.

In PowerShell:

```powershell
Get-FileHash .\myfile.zip -Algorithm SHA256
```

Run this on both computers for the corresponding files. A browser-only test does not replace this end-to-end check.

## Two PCs on a trusted LAN

To load the sender from the receiver's server:

```powershell
.\start.bat --host 0.0.0.0
```

On POSIX systems, use `sh start.sh --host 0.0.0.0`.

- Receiver: `http://localhost:5000/`.
- Sender PC: `http://RECEIVER_IP:5000/sender`.
- On Windows, use `ipconfig` to find the receiver's IPv4 address.

`0.0.0.0` is the listening address, not the address to enter in a remote browser. If needed, allow the port through the firewall's private-network profile. The server exposes reception, history and downloads; do not publish it directly to the Internet.

The LAN serves the interface. The file is encoded in the browser and carried over HDMI. To avoid a shared LAN entirely, use the local HTML file described above.

## Test with one PC

A loopback test still requires an HDMI output connected to a capture input:

1. Start the receiver.
2. Open `http://localhost:5000/sender/test` to enable the local test API explicitly.
3. Show the sender on the output connected to the card and receive on the same computer.

The sender and receiver share CPU/GPU resources, so this setup may be slower than two separate PCs. See [wiring and calibration](hardware-setup.md).

## Command-line usage

Install the CLI extras in each relevant clone:

```bash
uv sync --locked --extra all
```

On the receiver:

```bash
uv run --no-sync hdmi-recv 0 --mode fountain --profile balanced --output received_files
```

On the sender:

```bash
uv run --no-sync hdmi-send myfile.zip --mode fountain --profile balanced --screen 1
```

`0` and `1` are example device and monitor indices; adjust them to your setup. The receiver also accepts `name:Elgato`, `raw:1` or a local video path. Run each command with `--help` for all options.

| Command | Purpose |
| --- | --- |
| `hdmi-web` | Local web interface |
| `hdmi-send` / `hdmi-recv` | CLI transmission / reception |
| `hdmi-sender` / `hdmi-receiver` | Interactive consoles |
| `hdmi-calibrate` | Signal calibration |
| `hdmi-bench` | Software benchmark |

The launchers install only the `web` extra. After using them, run `uv sync --locked --extra all` again for CLI commands, or use `--extra dev` for development tools.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `uv` not found | Install uv and reopen the terminal. |
| `Repository not found` | Check repository access and the signed-in GitHub account. |
| Port 5000 is occupied | Restart with `--port 5001` and use that address. |
| No capture device detected | Check USB and drivers, click **Detect devices**, and close OBS or other apps using the card. |
| Black preview | Check the HDMI input/output, display and capture device; start the sender to produce a signal. |
| Visible frames but unstable decoding | Match protocol/profile/encoding on both sides; return to Fountain + Balanced + 2 bpc, then calibrate. |
| Speed makes no difference | Check the actual negotiated refresh rate throughout the path, including the capture card. |
| Sender continues after reception | Offline mode receives no acknowledgement; stop it manually after **Download**. |
| `/sender/app` returns 404 | Keep `sender.html` at the clone root or regenerate it. |
| CLI or pytest missing after a web launch | Reinstall the `all` or `dev` extra as appropriate. |

## Development and updates

In a clone with no local changes:

```bash
git pull --ff-only
uv sync --locked --extra dev
uv run --no-sync python tools/build_sender_html.py --check
```

`sender.html` is generated from `src/interfaces/browser_sender/`. To rebuild it:

```bash
uv run --no-sync python tools/build_sender_html.py
```

On Windows, run the [quality gate](testing.md):

```powershell
uv run --no-sync powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1
```

This guide does not claim hardware validation on Linux/macOS. Software tests and screenshots do not prove compatibility with every capture card.
