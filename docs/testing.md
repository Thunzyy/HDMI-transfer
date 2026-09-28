# Testing

## Standard local quality gate

Use this entry point to validate a branch locally:

```powershell
uv run powershell -ExecutionPolicy Bypass -File tools/run_quality_gate.ps1
```

It runs these checks in order:

```text
uv run pytest -m "not hardware"
uv run pytest tests/test_fountain_overhead.py tests/perf/test_fountain_budget.py -v
uv run python tools/build_sender_html.py --check
uv run hdmi-bench --profile balanced --mode fountain --no-json
```

## Optional local fallback

The full gate includes `tests/test_loopback.py`. Use `-SkipNativeLoopback` only as a local fallback when a development machine has a broken OpenCV installation.

## Targeted checks

```bash
uv run pytest tests/contracts -v
uv run pytest tests/test_send_session.py tests/test_receive_session.py -v
uv run pytest tests/test_capture_manager.py tests/test_threaded_capture.py -v
uv run pytest tests/test_web_app_factory.py tests/test_server_receive_file_api.py -v
uv run pytest tests/test_sender_build.py tests/test_sender_html_magic.py -v
uv run pytest tests/test_fountain_overhead.py tests/perf/test_fountain_budget.py -v
```

## Docker smoke test

With Docker and Python available, run:

```bash
python tools/docker_smoke.py
```

This builds the image and starts a uniquely named temporary Compose project. It checks health, web pages, APIs, non-root execution, downloads and file persistence after container recreation. It then removes only its own test containers and volume. GitHub Actions runs this check on Linux; the Python quality gate runs on Windows. This does not test physical HDMI reception.

## Hardware validation

Hardware tests are excluded from standard CI. Run them manually on a prepared machine:

1. `hdmi-calibrate --profile balanced loopback <capture-index>`
2. `uv run hdmi-recv <capture-index> --profile balanced`
3. `uv run hdmi-send <payload> --mode sequential --profile balanced --screen <screen-index>`
4. `uv run hdmi-send <payload> --mode fountain --profile balanced --screen <screen-index>`
5. `uv run hdmi-web`, then check `/`, `/sender`, `/history` and `/settings`.

## Test coverage

- Protocol contracts and Python/browser compatibility.
- Shared send/receive sessions.
- Capture management and backoff after failed reads.
- Flask interfaces and CLI wrappers.
- Fountain performance budgets.
- Deterministic PRNG/RSD properties.

## Completion criteria

A branch is ready to merge when the quality gate and generated-sender check pass, and any hardware checks required by the change have been run on a properly equipped machine. Record software and hardware results separately.
