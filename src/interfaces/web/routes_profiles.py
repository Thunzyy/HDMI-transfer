"""Sender-PC profile and auto receive HTTP routes."""

from __future__ import annotations

from flask import Flask, jsonify, request

from hdmi_transfer.adapters.calibration_store import CalibrationStore
from hdmi_transfer.adapters.profile_store import ProfileError


def register_profile_routes(app: Flask) -> None:
    store = app._profile_store

    def _error(message: str, status: int):
        return jsonify({"error": message}), status

    def _body() -> dict:
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def _activate(profile_id: int | None):
        try:
            store.set_active_id(profile_id)
        except ProfileError as exc:
            return _error(str(exc), 404)
        app._auto_receive.on_profile_changed()
        return jsonify({"active_profile_id": store.get_active_id()})

    @app.route("/api/sender-profiles", methods=["GET", "POST"])
    def api_sender_profiles():
        if request.method == "GET":
            return jsonify({"profiles": store.list(), "active_profile_id": store.get_active_id()})
        try:
            return jsonify(store.create(_body())), 201
        except ProfileError as exc:
            return _error(str(exc), 400)

    @app.route("/api/sender-profiles/<int:profile_id>", methods=["PUT", "DELETE"])
    def api_sender_profile(profile_id: int):
        if store.get(profile_id) is None:
            return _error("Unknown sender PC", 404)
        if request.method == "DELETE":
            store.delete(profile_id)
            CalibrationStore().delete_profile(profile_id)
            app._auto_receive.on_profile_changed()
            return jsonify({"status": "deleted", "id": profile_id})
        try:
            updated = store.update(profile_id, _body())
        except ProfileError as exc:
            return _error(str(exc), 400)
        if store.get_active_id() == profile_id:
            app._auto_receive.on_profile_changed()
        return jsonify(updated)

    @app.route("/api/sender-profiles/<int:profile_id>/activate", methods=["POST"])
    def api_sender_profile_activate(profile_id: int):
        return _activate(profile_id)

    @app.route("/api/sender-profiles/active", methods=["POST"])
    def api_sender_profile_active():
        value = _body().get("id")
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            return _error("Expected {\"id\": <profile id or null>}", 400)
        return _activate(value)

    @app.route("/api/receive/auto", methods=["GET", "POST"])
    def api_receive_auto():
        if request.method == "POST":
            enabled = _body().get("enabled")
            if not isinstance(enabled, bool):
                return _error("Expected {\"enabled\": true|false}", 400)
            store.set_auto_receive(enabled)
            if enabled:
                app._auto_receive.clear_pause()
        return jsonify(app._auto_receive.status())
