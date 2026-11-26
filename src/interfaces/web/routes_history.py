"""Transfer history HTTP routes backed by the receiver's SQLite store."""

from __future__ import annotations

from flask import Flask, jsonify, request


def register_history_routes(app: Flask) -> None:
    @app.route("/api/history", methods=["GET", "DELETE"])
    def api_history():
        store = app._history_store
        if request.method == "DELETE":
            return jsonify({"status": "cleared", "deleted": store.clear()})
        return jsonify(store.list())

    @app.route("/api/history/<int:entry_id>", methods=["DELETE"])
    def api_history_entry(entry_id: int):
        if not app._history_store.delete(entry_id):
            return jsonify({"error": "History entry not found", "id": entry_id}), 404
        return jsonify({"status": "deleted", "id": entry_id})

    @app.route("/api/history/import", methods=["POST"])
    def api_history_import():
        payload = request.get_json(silent=True) or {}
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return jsonify({"error": "Expected {\"entries\": [...]}"}), 400
        return jsonify({"imported": app._history_store.import_entries(entries)})
