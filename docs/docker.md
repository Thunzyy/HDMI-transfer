# Run HDMI Transfer with Docker

[Back to the README](../README.md)

## Quick start

Install Docker Engine with Compose v2 on Linux, or Docker Desktop using Linux containers on Windows/macOS. Start Docker, clone this repository with an authorized GitHub account, then run:

```bash
docker compose up --build -d --wait
```

Open **http://localhost:5000**. Compose waits for the web health check before returning. The image includes Python, the locked web/receiver dependencies, OpenCV and the standalone sender; no local Python or uv installation is required. The first build downloads the base image and dependencies. Subsequent starts reuse them.

The container runs as a non-root user. A single Waitress process owns capture state, with threads for HTTP requests, preview and events. Do not scale this service to multiple replicas against the same capture device or received-files volume.

## What runs where?

| Component | Location |
| --- | --- |
| Receiver, capture backend and file storage | Docker container |
| Receive, history and settings UI | Your browser at `http://localhost:5000` |
| Sender | Browser on the computer with the HDMI output |
| Physical capture card | Connected to the Docker host and explicitly passed to the container |

Without a mapped card, the interface still starts and the device list can be empty. This is useful for trying the UI, but it is not a physical HDMI transfer. Keep the sender browser on the sending computer; there is no desktop display server in the image.

Docker Desktop does not automatically provide the host's Windows/macOS capture drivers or USB devices to a Linux container. Advanced USB/IP passthrough depends on the backend and device. See [Docker's USB/IP documentation](https://docs.docker.com/desktop/features/usbip/); this project does not claim that every capture card works through it. For a Windows receiver with a locally attached card, use `start.bat` for straightforward access to native drivers.

## Linux capture card

On **native Linux Docker Engine**, first confirm that the card works on the host and identify its video capture node. Some cards expose multiple nodes; choose the one that actually carries video.

```bash
ls -l /dev/video*
export HDMI_VIDEO_DEVICE=/dev/video0
export HDMI_VIDEO_GID=$(stat -c '%g' "$HDMI_VIDEO_DEVICE")
docker compose -f compose.yaml -f compose.capture.yaml up --build -d --wait
```

The selected host device is mapped to `/dev/video0` inside the container. Its numeric group ID is added to the container user so it can access the device without running privileged. The variable is required to avoid silently assuming the wrong group. [Compose device mapping reference](https://docs.docker.com/reference/compose-file/services/#devices).

Open **Receive**, detect devices and select the card. Start with **Fountain + Balanced + 2 bpc** on both ends. Use the same two `-f` arguments for subsequent Compose operations that recreate the capture service. If the device path changes after reconnecting USB, update the variable and recreate the container.

No physical capture-card test is implied by the software smoke test below. Driver support, USB bandwidth and the actual HDMI signal still need to be checked on your host.

## Files and persistence

Received files live in `/app/received_files`, backed by the Compose `received-files` named volume. They survive container restarts and recreation, including `docker compose down` followed by `up`.

- Download files through the browser's **History** page.
- **Reveal in file manager** is a native desktop feature; use **Download** when running Docker.
- `docker compose down --volumes` **deletes received files**. Use ordinary `down` to keep them.
- Your existing host `received_files/` directory is not imported or modified.

To export all received files into a new host folder:

```bash
docker compose cp hdmi-transfer:/app/received_files ./docker-received-backup
```

## Port and LAN access

The default binding is `127.0.0.1:5000`, accessible only from the Docker host. Put overrides in a local `.env` file in the repository root (already ignored by Git):

```dotenv
HDMI_PORT=5001
HDMI_BIND_ADDRESS=127.0.0.1
```

Reapply with `docker compose up -d --wait`, then open `http://localhost:5001`.

For a trusted LAN, set `HDMI_BIND_ADDRESS=0.0.0.0` and load `http://RECEIVER_IP:5001/sender` from the sender PC. This exposes receiver controls and received files to that network; it is not an authenticated public service. The LAN serves the UI, while the file payload travels over HDMI. A copied local `sender.html` avoids needing a shared network.

## Everyday commands

```bash
docker compose ps                  # Service and health status
docker compose logs --tail 100     # Recent server logs
docker compose stop               # Stop, retain data
docker compose start              # Start existing container
docker compose down               # Remove container/network, retain data
```

To update a clean clone:

```bash
git pull --ff-only
docker compose up --build -d --wait
```

If port 5000 is occupied, change `HDMI_PORT`. If the service is unhealthy, inspect `docker compose logs`. If no devices are detected, verify that the host has a usable capture node and that the Linux override and group ID are applied.

## Reproducible software test

With Docker running and Python 3.11+ available on the test host:

```bash
python tools/docker_smoke.py
```

This builds the real image, starts an isolated Compose project on an automatically assigned localhost port, checks health, seven pages/assets, device and receiver APIs, and non-root execution. It writes a harmless test file into its own new volume, verifies the download, recreates the container and checks that the file survives byte-for-byte. It removes only that uniquely named test project's containers and volume afterwards. No real capture card or existing received files are used.

The same test runs in GitHub Actions on Linux. Browser rendering and physical hardware remain separate validation steps.
