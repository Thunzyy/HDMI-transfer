# Calibration and saved setups

The receiver learns the position and scale of the video grid before accepting a
file. It checks three distinct calibration frames, including their known color
pattern, then saves the sampling geometry. The recommended configuration is
**Fountain, Balanced, 2 bits per color channel** in the web interface and CLI.

## First transfer

1. Connect the HDMI output to the capture card and select the card on the receiver.
2. Match the profile and encoding on both computers. Start the receiver first.
3. Load the file in `sender.html` and click **Start transmission**. Move this window
   to the HDMI display before starting. The full-screen pattern must remain unobstructed.
4. For an offline transfer, wait until the receiver reports **Calibration saved**
   or a verified signal, then press **Enter on the sending computer**. No file data
   is emitted before that first confirmation. The sender needs at least three
   seconds of pattern display before accepting Enter.
5. The receiver reconstructs the file and checks its SHA-256 hash. Confirm that
   result before using the received file.

The explicit local test mode with receiver API access confirms calibration
automatically. It requires a newly started reception; a previous completed or
already calibrated session cannot acknowledge a new transfer. Failed or silent
API requests stop the sender with an error, without sending the file.

## Subsequent transfers

On the same capture setup, the receiver first tries its saved sampling geometry.
Three new, distinct calibration frames verify that it still works. The expensive
geometry search runs only if those parameters fail.

The offline sender remembers the setup that the user confirmed. With the same
profile, encoding, monitor position and displayed dimensions, it emits a short
one-second verification pattern before continuing automatically. The receiver
still verifies the pattern; the sender cannot observe its result over a
one-way HDMI connection. If the receiver remains in calibration, stop sending
and recalibrate both sides. No offline completion message proves successful
reception: use the receiver's SHA-256 result.

Saved geometry reduces repeated computation; it does not increase the physical
refresh rate or guarantee a particular transfer speed.

## Changed setup or failed verification

- **Receiver: Recalibrate** restarts reception while ignoring the cached hint.
- **Sender: Recalibrate** forgets the offline confirmation and requires Enter
  again after the receiver confirms readiness.
- The receiver cache separates device identity, opened source, capture backend,
  video profile, encoding and incoming image dimensions. A changed configuration
  uses another entry. A corrupt or unwritable cache does not prevent calibration.
- The cache is a hint. Even a matching entry is checked against the current signal.

The application does not measure a full bit-error-rate distribution during this
short check. It validates the calibration pattern and then validates each data
frame and the reconstructed file.

## CLI

```bash
hdmi-recv 0 --profile balanced --mode fountain --bpc 2
hdmi-send payload.bin --profile balanced --mode fountain --bpc 2 --screen 1
```

The CLI sender also displays the pattern and waits for Enter the first time. An
explicitly confirmed matching display setup gets the short check next time.
Use `--recalibrate` on either command to force a fresh setup. For compatibility
with older senders or specialist diagnostics, `--no-calibration` bypasses that
phase explicitly. Video-file reception keeps its existing playback path.

## Storage

- Receiver geometry: `~/.hdmi-transfer/calibration.json` (versioned, up to 64 entries).
- CLI preferences and sender confirmation: `~/.hdmi-transfer/settings.json`.
- Browser preferences and offline confirmation: local browser storage. Clearing
  that storage or using another browser requires confirmation again.
- `HDMI_TRANSFER_STATE_DIR` overrides the native state directory.
- Docker Compose persists receiver state in the separate `calibration-state`
  volume mounted at `/app/state`. Received files remain in `received-files`.

## Validation

Run the normal quality gate, then the browser checks:

```powershell
uv run --no-sync powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1
uv run --no-sync pytest tests/browser/test_sender_calibration.py --browser -v
```

The browser checks run real Chrome without a capture device. They exercise
first use, saved setup, explicit recalibration, connected confirmation and silent
or stale receivers; actual canvas calibration pixels are decoded by Python.
Hardware throughput requires a separate measurement on the intended HDMI chain.
