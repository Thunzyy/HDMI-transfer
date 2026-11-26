import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HDMI_TRANSFER_STATE_DIR", str(tmp_path))
    from hdmi_transfer.interfaces.web.app_factory import create_app

    app = create_app(runtime=False)
    return app.test_client()


def new_profile(client, name="PC BNP", **overrides):
    body = {"name": name, "device_name": "Elgato 4K X", "device_index": 0,
            "profile": "balanced", "mode": "fountain", "bpc": 2, "preview_quality": 45}
    body.update(overrides)
    return client.post("/api/sender-profiles", json=body)


def test_profile_crud_roundtrip(client):
    created = new_profile(client)
    assert created.status_code == 201
    profile_id = created.get_json()["id"]

    listing = client.get("/api/sender-profiles").get_json()
    assert [p["name"] for p in listing["profiles"]] == ["PC BNP"]
    assert listing["active_profile_id"] is None

    updated = client.put(f"/api/sender-profiles/{profile_id}", json={"bpc": 3})
    assert updated.status_code == 200
    assert updated.get_json()["bpc"] == 3

    assert client.delete(f"/api/sender-profiles/{profile_id}").status_code == 200
    assert client.get("/api/sender-profiles").get_json()["profiles"] == []


def test_duplicate_name_returns_400(client):
    new_profile(client)
    response = new_profile(client, name="pc bnp")
    assert response.status_code == 400
    assert "already exists" in response.get_json()["error"]
    assert new_profile(client, name="  ").status_code == 400


def test_unknown_profile_returns_404(client):
    assert client.put("/api/sender-profiles/99", json={"bpc": 1}).status_code == 404
    assert client.delete("/api/sender-profiles/99").status_code == 404
    assert client.post("/api/sender-profiles/99/activate").status_code == 404


def test_activate_sets_active_and_status_reports_it(client):
    profile_id = new_profile(client).get_json()["id"]
    response = client.post(f"/api/sender-profiles/{profile_id}/activate")
    assert response.status_code == 200
    assert client.get("/api/sender-profiles").get_json()["active_profile_id"] == profile_id
    status = client.get("/api/receive/status").get_json()
    assert status["active_profile_id"] == profile_id
    assert status["auto_receive"]["enabled"] is False


def test_deactivate_with_null(client):
    profile_id = new_profile(client).get_json()["id"]
    client.post(f"/api/sender-profiles/{profile_id}/activate")
    assert client.post("/api/sender-profiles/active", json={"id": None}).status_code == 200
    assert client.get("/api/sender-profiles").get_json()["active_profile_id"] is None


def test_auto_toggle_roundtrip(client):
    assert client.get("/api/receive/auto").get_json()["enabled"] is False
    on = client.post("/api/receive/auto", json={"enabled": True})
    assert on.status_code == 200
    assert on.get_json()["enabled"] is True
    assert client.get("/api/receive/auto").get_json()["enabled"] is True
    assert client.post("/api/receive/auto", json={"enabled": "yes"}).status_code == 400


def test_turning_auto_on_clears_a_pause(client):
    client.application._auto_receive.pause("Stopped by user")
    client.post("/api/receive/auto", json={"enabled": True})
    assert client.get("/api/receive/auto").get_json()["paused"] is False


def test_delete_active_profile_clears_active_and_calibration(client, tmp_path):
    from hdmi_transfer.adapters.calibration_store import CalibrationStore

    profile_id = new_profile(client).get_json()["id"]
    client.post(f"/api/sender-profiles/{profile_id}/activate")
    CalibrationStore().save("k", (0, 0, 1.0, 1.0), sender_profile=profile_id)
    assert client.delete(f"/api/sender-profiles/{profile_id}").status_code == 200
    assert client.get("/api/sender-profiles").get_json()["active_profile_id"] is None
    assert CalibrationStore().load("k") is None
