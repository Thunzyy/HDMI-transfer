"""Launch the HDMI Exfil web application.

Usage::

    python -m hdmi_exfil.web
    python -m hdmi_exfil.web --port 8080
    python -m hdmi_exfil.web --host 0.0.0.0
"""

from __future__ import annotations

import argparse

from hdmi_exfil.web.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hdmi-web",
        description="HDMI Exfil web application",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    print(f"HDMI Exfil Web: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
