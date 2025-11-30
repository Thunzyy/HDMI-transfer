# HDMI Exfiltration Prototype

This project demonstrates high-speed data transfer via HDMI by encoding binary data into video frames.

## Files

- `sender.py`: Run this on the source machine. It reads a file and displays it as a sequence of QR-like images.
- `receiver.py`: Run this on the destination machine (connected to the capture card). It reads the video feed and reconstructs the file.
- `common.py`: Configuration settings (Resolution, Block Size).
- `test_loopback.py`: Verifies the logic without hardware.

## Usage

### 1. Setup

- **Source Machine**: Connect HDMI output to the Capture Card input.
- **Destination Machine**: Connect Capture Card via USB/PCIe. Ensure it's recognized as a camera device (e.g., `/dev/video0` or index `0` or `1` on Windows).

### 2. Configure

Edit `common.py` if needed:

- `WIDTH`, `HEIGHT`: Set to your capture resolution (e.g., 1920, 1080).
- `BLOCK_SIZE`: Default is 8. Increase if you see corruption (e.g., to 16 or 32), decrease for higher speed if the signal is clean.

### 3. Run Sender

On the source machine:

```bash
python sender.py my_secret_file.zip
```

It will show a calibration screen. **Do not press a key yet.**

### 4. Run Receiver

On the destination machine:

```bash
# Replace '0' with your capture card device index
python receiver.py 0 output_file.zip
```

The receiver will start listening.

### 5. Start Transmission

Press any key on the **Sender** window to start the flashing sequence.

### 6. Finish

When the sender shows "DONE", check the receiver output.

## Troubleshooting

- **Corruption**: If the output file is corrupted, try increasing `BLOCK_SIZE` in `common.py` (must be same on both sides).
- **Black Bars**: If the capture card adds black bars, you might need to adjust the `sample_frame` function in `receiver.py` to crop the image.
