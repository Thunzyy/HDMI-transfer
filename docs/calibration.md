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
   seconds of unobstructed pattern display before accepting Enter.
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

Entering native browser fullscreen can briefly cover the signal with a browser
notification. After a new successful fullscreen transition, the sender displays
the calibration pattern for five seconds to let that notification clear, then
starts the normal check: one further second for a saved setup, or three seconds
before the first Enter confirmation. Connected mode also starts its calibration
timeout and encoding fallback timers after this settling interval. This is a
display allowance, not an acknowledgement from the receiver. Browser or system
notifications that remain longer still require stopping and recalibrating.

When the browser is already fullscreen (including F11 or kiosk mode), the sender
does not request native fullscreen again and retains the one-second saved check.

Saved geometry reduces repeated computation; it does not increase the physical
refresh rate or guarantee a particular transfer speed.

## Changed setup or failed verification

- **Calibrate without a file**: click **Calibrate** on the receiver, then
  **Calibrate** on the sender. The sender shows the pattern with no file
  selected. The receiver ignores the cached hint, validates three fresh frames,
  saves the geometry, stores the encoding the sender really uses (bpc) in the
  selected sender PC profile, and stops. Offline, press Enter on the sender once
  the receiver shows *Calibrated*; with the receiver API the sender stops by
  itself. The next **Start** (or auto receive) reuses this calibration at once.
- **Sender: Calibrate** also forgets the previous offline confirmation.
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

## Sender PC profiles and auto receive

When several PCs send to the same receiver (for example a work PC and a
personal PC), create one **sender PC** per machine in Settings. A sender PC
keeps its capture device, profile, mode, encoding and preview quality, and its
own calibration. Pick it in the Receive sidebar; changing a setting there saves
it to that PC.

When a transfer starts, the receiver tries the selected PC's saved geometry
first, then the geometry of the other sender PCs on the same capture card and
profile. If one of them matches the live signal, the receiver switches to that
PC and says so in the log. If none matches, it calibrates as usual. A saved
geometry is still only a hint: three fresh calibration frames must confirm it.

**Auto receive** (switch in the Receive sidebar) keeps the receiver armed for
the selected PC, with or without the page open, and re-arms it after each
file. Stop or Reset pauses it. After 3 receptions in a row that end without a
file, it pauses and shows why. Turn the switch off and on to resume. While it
is on, the web server holds the capture card, so turn it off before using
`hdmi-recv`.

## Storage

- Receiver geometry: `~/.hdmi-transfer/calibration.json` (versioned, up to 64 entries).
- Sender PCs, the selected PC and the auto receive switch: `~/.hdmi-transfer/profiles.sqlite3`.
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
