"""Launch the HDMI Transfer web application.

Usage::

    python -m hdmi_transfer.web
    python -m hdmi_transfer.web --port 8080
    python -m hdmi_transfer.web --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import contextlib

from hdmi_transfer.interfaces.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hdmi-web",
        description="HDMI Transfer web application",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app = create_app()
    print(f"HDMI Transfer Web: http://{args.host}:{args.port}")
    try:
        app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    except KeyboardInterrupt:
        print("\nStopping HDMI Transfer web server...")
    finally:
        with contextlib.suppress(Exception):
            app.shutdown_runtime()


if __name__ == "__main__":
    main()
