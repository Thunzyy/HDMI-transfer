# Hardware setup

## Transfer between two PCs

Start with two computers:

```text
Sender PC (HDMI output) → HDMI cable → capture card (HDMI input) → USB → receiver PC
```

A capture card is required because a computer's HDMI port is usually an output. Prepare the local HTML sender and install the receiver using the [getting-started guide](getting-started.md). Start with Fountain + Balanced + 2 bpc on both sides.

## Development with one PC

You can develop and validate the path using a single-PC loopback:

```text
GPU ─── HDMI ──► secondary display (sender)
 │
 └───── HDMI ──► Elgato 4K X ──► same PC over USB
```

The secondary display and capture card must receive the same signal.

## Windows configuration

1. Open **Settings > System > Display**.
2. Identify the Elgato as an additional display.
3. Choose to duplicate the secondary display onto it.
4. Verify that the sender appears on the duplicated display and the card captures it.

## Find the capture index

With FFmpeg installed:

```powershell
ffmpeg -list_devices true -f dshow -i dummy 2>&1 | findstr "video"
```

Or run this Python snippet in the project's environment:

```python
import cv2

for i in range(10):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Index {i}: {width}x{height}")
    cap.release()
```

## Find the sender monitor index

Run this Python snippet in the project's environment:

```python
from hdmi_transfer.sender.display.monitors import get_monitors

for i, monitor in enumerate(get_monitors()):
    print(
        f"Monitor {i}: {monitor['width']}x{monitor['height']} "
        f"at ({monitor['left']}, {monitor['top']})"
    )
```

## Calibration

Calibrate before an actual transfer:

```bash
uv run --no-sync hdmi-calibrate --profile balanced loopback 1
```

Place `--profile` before the subcommand. Replace `1` with your capture index.

| SNR | Quality | Action |
| --- | --- | --- |
| > 30 dB | EXCELLENT | Ready for testing |
| 20–30 dB | GOOD | Usable as configured |
| 10–20 dB | FAIR | Reduce FPS and check the signal path |
| < 10 dB | POOR | Check display duplication, wiring and capture source |

## Profiles

| Profile | Resolution | Target FPS | Use |
| --- | --- | --- | --- |
| `balanced` | 1080p | 60 | Default starting point |
| `quality` | 4K | 30 | Experiments on a 4K-compatible path |
| `speed` | 1080p | 240 | Only when the display, card and receiver support the cadence |

Changing profiles does not guarantee better signal quality. Match both ends and verify the negotiated resolution and frame rate.

## Docker on native Linux

Confirm the card works on the Linux host, then select its video capture node:

```bash
ls -l /dev/video*
export HDMI_VIDEO_DEVICE=/dev/video0
export HDMI_VIDEO_GID=$(stat -c '%g' "$HDMI_VIDEO_DEVICE")
docker compose -f compose.yaml -f compose.capture.yaml up --build -d --wait
```

The selected host device appears as `/dev/video0` in the container. Its numeric group is added to the non-root container user. Some cards expose multiple nodes; choose the video node that actually carries the signal. Keep both `-f` arguments when recreating the capture service.

Docker Desktop does not automatically expose host USB capture cards. For native Windows capture, use `start.bat`. Driver/device compatibility still requires a physical test.

## Minimum manual validation

1. `hdmi-calibrate --profile balanced loopback <capture-index>`
2. `uv run hdmi-recv <capture-index> --profile balanced`
3. `uv run hdmi-send test.bin --mode sequential --profile balanced --screen <screen-index>`
4. `uv run hdmi-send test.bin --mode fountain --profile balanced --screen <screen-index>`
5. `uv run hdmi-web`, then verify the receiver UI and `/sender`.

## Common symptoms

- No receiver signal: check the capture index and display duplication.
- Low SNR: check the selected display, cable and capture source.
- Falling FPS during loopback: the sender and receiver share resources; return to `balanced`.
- Unstable decoding: check calibration first, then block size and profile.
