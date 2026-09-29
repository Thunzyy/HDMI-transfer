"""One process owns capture state; threads serve the UI, events and preview."""

import signal

from waitress import create_server

from hdmi_transfer.interfaces.web import create_app


def main():
    app = create_app(output_dir="/app/received_files")
    server = create_server(app, host="0.0.0.0", port=5000, threads=16)

    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("HDMI Transfer: listening on port 5000", flush=True)
    try:
        server.run()
    finally:
        server.close()
        app.shutdown_runtime()


if __name__ == "__main__":
    main()
