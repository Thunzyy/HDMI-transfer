"""Build and test Compose in a disposable project, without capture hardware.

Run with plain Python: python tools/docker_smoke.py
Only this run's uniquely named containers and volume are removed afterwards.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from urllib.request import urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    project = f"hdmi-smoke-{uuid4().hex[:10]}"
    env = dict(os.environ, HDMI_PORT="0", HDMI_BIND_ADDRESS="127.0.0.1")
    command = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.yaml")]

    def compose(*args: str, capture: bool = False) -> str:
        result = subprocess.run(
            [*command, *args], cwd=ROOT, env=env, check=True,
            text=True, stdout=subprocess.PIPE if capture else None,
        )
        return (result.stdout or "").strip()

    def address() -> str:
        return "http://" + compose("port", "hdmi-transfer", "5000", capture=True)

    def read(base: str, path: str) -> bytes:
        with urlopen(base + path, timeout=45) as response:
            assert response.status == 200, (path, response.status)
            return response.read()

    try:
        compose("up", "--build", "-d", "--wait", "--wait-timeout", "120")
        base = address()
        for path, marker in [
            ("/", b"HDMI Transfer"),
            ("/sender", b"sender-frame"),
            ("/sender/app", b"Start transmission"),
            ("/sender/test", b"sender-frame"),
            ("/settings", b"Settings"),
            ("/history", b"History"),
            ("/static/images/logo.svg", b"<svg"),
        ]:
            assert marker in read(base, path), path
        assert json.loads(read(base, "/api/receive/status"))["active"] is False
        assert isinstance(json.loads(read(base, "/api/devices")), list)
        assert "balanced" in json.loads(read(base, "/api/profiles"))
        assert json.loads(read(base, "/api/receive/files")) == []
        compose("exec", "-T", "hdmi-transfer", "python", "-c",
                "import os; assert os.getuid() != 0")
        print("PASS: healthy, non-root, seven web pages/assets and receiver APIs", flush=True)

        # This is a test file in this run's new volume, never a real received file.
        payload = "HDMI Transfer Docker persistence test\n"
        compose("exec", "-T", "hdmi-transfer", "python", "-c",
                "from pathlib import Path; "
                f"Path('/app/received_files/docker-smoke.txt').write_text({payload!r})")
        assert read(base, "/api/receive/download/docker-smoke.txt") == payload.encode()
        compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "120")
        base = address()
        assert read(base, "/api/receive/download/docker-smoke.txt") == payload.encode()
        files = json.loads(read(base, "/api/receive/files"))
        assert [item["filename"] for item in files] == ["docker-smoke.txt"]
        print("PASS: file download and persistence after container recreation", flush=True)
    except Exception:
        compose("logs", "--tail", "100")
        raise
    finally:
        compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
