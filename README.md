# HDMI Exfiltration Prototype

A proof-of-concept tool to transfer files (exfiltrate data) via HDMI video signals. The "Sender" encodes files into a sequence of QR-like video frames, which are displayed on a monitor. The "Receiver" captures this video feed (via a Capture Card) and decodes it back into the original file.

## 📋 Prerequisites

- **Python 3.8+** installed on both Sender and Receiver machines.
- **Hardware**:
  - **Sender PC**: Must have an HDMI output.
  - **Receiver PC**: Must have a Video Capture Card (e.g., Elgato Cam Link, generic USB capture card) connected.
  - **HDMI Cable**: Connecting the Sender's output to the Capture Card's input.

## 🛠️ Installation

1.  **Clone or download** this repository on both machines.
2.  **Install dependencies**:
    Open a terminal in the project folder and run:
    ```bash
    pip install -r requirements.txt
    ```

## 🚀 Usage

### 1. Receiver (Capture Side)

Start the receiver **first** so it's ready to catch the transmission.

```bash
# Syntax: python receiver.py <camera_index> [output_directory]

# Example: Listen on camera index 2 and save to default folder
python receiver.py 2

# Example: Listen on camera index 0 and save to "C:\Downloads"
python receiver.py 0 "C:\Downloads"
```

- **Note**: Use `python list_devices.py` (if available) or trial-and-error (0, 1, 2...) to find your capture card index.
- **Visual Check**: A window will open showing the capture feed with a **yellow grid**. Ensure the grid aligns roughly with the incoming video blocks.

### 2. Sender (Source Side)

Run the sender to start transmitting a file or folder.

```bash
# Syntax: python sender.py <file_or_folder> [fps]

# Example: Send a file at default 30 FPS
python sender.py secret.pdf

# Example: Send a folder (auto-zipped) at 60 FPS
python sender.py "C:\My Documents\Project" 60
```

- **Calibration**: A crosshair screen will appear first.
- **Start**: Ensure the Receiver is running, then **press SPACE** on the Sender window to begin.
- **Speed**: If the Receiver misses frames (corrupted file), try lowering the FPS (e.g., `python sender.py file.txt 15`).

## ⚙️ Configuration (`common.py`)

You can tweak advanced settings in `common.py`:

- `WIDTH` / `HEIGHT`: Resolution (Default 1920x1080). Must match your capture card settings.
- `BLOCK_SIZE`: Size of pixel blocks (Default 8). Larger = slower but more robust against compression.

## ⚠️ Troubleshooting

- **"No data received"**: Ensure the Sender window is in focus when you press SPACE.
- **Corrupted Files**:
  - Lower the FPS on the Sender.
  - Increase `BLOCK_SIZE` in `common.py` (must be done on BOTH machines).
  - Ensure the Capture Card is not applying heavy compression (MJPEG artifacts can break decoding).
