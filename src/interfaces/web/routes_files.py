"""File management HTTP routes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_file


def _resolve_output_file(app: Flask, filename: str) -> tuple[str, str]:
    safe = os.path.basename(filename)
    path = os.path.abspath(os.path.join(app.config["OUTPUT_DIR"], safe))
    return safe, path


def _reveal_in_file_manager(path: str) -> tuple[str, str]:
    target = Path(path).resolve()
    parent = target.parent

    if target.exists():
        if sys.platform == "win32":
            subprocess.Popen([
                "explorer.exe",
                "/select,",
                os.path.normpath(str(target)),
            ])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(parent)])
        return "file", str(target)

    if not parent.exists():
        raise FileNotFoundError(f"Directory not found: {parent}")

    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", os.path.normpath(str(parent))])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(parent)])
    else:
        subprocess.Popen(["xdg-open", str(parent)])
    return "directory", str(parent)


def register_file_routes(app: Flask) -> None:
    @app.route("/api/receive/download/<path:filename>")
    def api_download(filename):
        _, path = _resolve_output_file(app, filename)
        if not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404
        return send_file(path, as_attachment=True)

    @app.route("/api/receive/files")
    def api_receive_files():
        root = Path(app.config["OUTPUT_DIR"]).resolve()
        if not root.exists():
            return jsonify([])

        files: list[dict] = []
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not child.is_file():
                continue
            stat = child.stat()
            files.append({
                "filename": child.name,
                "system_path": str(child.resolve()),
                "size": stat.st_size,
                "modified_ms": int(stat.st_mtime * 1000),
            })
        return jsonify(files)

    @app.route("/api/receive/file/<path:filename>", methods=["GET", "DELETE"])
    def api_receive_file(filename):
        safe, path = _resolve_output_file(app, filename)
        exists = os.path.isfile(path)

        if request.method == "GET":
            payload = {
                "filename": safe,
                "system_path": path,
                "exists": exists,
            }
            if exists:
                payload["size"] = os.path.getsize(path)
            return jsonify(payload)

        if not exists:
            return jsonify({
                "error": "File not found",
                "filename": safe,
                "system_path": path,
                "exists": False,
            }), 404

        try:
            os.remove(path)
        except OSError as exc:
            return jsonify({
                "error": str(exc),
                "filename": safe,
                "system_path": path,
                "exists": True,
            }), 409
        return jsonify({
            "status": "deleted",
            "filename": safe,
            "system_path": path,
            "exists": False,
        })

    @app.route("/api/receive/file/<path:filename>/reveal", methods=["POST"])
    def api_receive_file_reveal(filename):
        safe, path = _resolve_output_file(app, filename)
        try:
            opened_kind, opened_path = _reveal_in_file_manager(path)
        except FileNotFoundError:
            return jsonify({
                "error": "File location not found",
                "filename": safe,
                "system_path": path,
                "exists": False,
            }), 404
        except OSError as exc:
            return jsonify({
                "error": str(exc),
                "filename": safe,
                "system_path": path,
                "exists": os.path.isfile(path),
            }), 409

        return jsonify({
            "status": "revealed",
            "opened": opened_kind,
            "opened_path": opened_path,
            "filename": safe,
            "system_path": path,
            "exists": os.path.isfile(path),
        })
