# HDMI Transfer screenshots

These PNGs show the application's actual pages in Chrome, without interface retouching or injected statistics.

| File | State shown |
| --- | --- |
| `receiver.png` | Idle receiver with no capture device exposed. |
| `sender.png` | Offline sender with `hello-hdmi.txt` loaded; transmission has not started. |
| `settings.png` | Settings page. |

The server uses an empty temporary directory with hardware detection disabled. The script does not read real transfer history or open a capture card. These images illustrate the interface; they are not evidence of a completed hardware transfer or measured throughput.

The sender's **Throughput** value is an estimate calculated by the interface, not a capture-card measurement.

## Regenerate

Install Chrome, then run from the repository root:

```bash
uv sync --locked --extra dev
uv run --no-sync python tools/capture_docs.py
```

Selenium Manager may download the Chrome driver on the first run. The script starts a local server on a free port, opens an isolated headless browser, captures the three pages and releases its resources. It fails on severe console errors. Visually review the screenshots before publishing them.
