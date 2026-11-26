import time

import pytest

from hdmi_transfer.adapters.profile_store import ProfileError, ProfileStore


def profile(name="PC BNP", **overrides):
    data = {
        "name": name, "device_name": "Elgato 4K X", "device_index": 0,
        "profile": "balanced", "mode": "fountain", "bpc": 2, "preview_quality": 45,
    }
    data.update(overrides)
    return data


@pytest.fixture
def store(tmp_path):
    return ProfileStore(tmp_path / "profiles.sqlite3")


def test_create_list_get_roundtrip(store):
    created = store.create(profile())
    assert created["id"] > 0
    assert created["name"] == "PC BNP"
    assert store.get(created["id"]) == created
    assert [p["id"] for p in store.list()] == [created["id"]]


def test_name_is_required_and_unique(store):
    store.create(profile("PC BNP"))
    for name in ("", "   ", "pc bnp", " PC BNP "):
        with pytest.raises(ProfileError):
            store.create(profile(name))


@pytest.mark.parametrize("field, value", [
    ("profile", "x"), ("mode", "fast"), ("bpc", 4), ("preview_quality", 50),
])
def test_invalid_values_rejected(store, field, value):
    with pytest.raises(ProfileError):
        store.create(profile(**{field: value}))


def test_update_changes_updated_at_and_fields(store):
    created = store.create(profile())
    time.sleep(0.01)
    updated = store.update(created["id"], {"bpc": 3, "name": "PC BNP 2"})
    assert updated["bpc"] == 3
    assert updated["name"] == "PC BNP 2"
    assert updated["mode"] == "fountain"
    assert updated["updated_at"] > created["updated_at"]
    assert store.update(9999, {"bpc": 1}) is None


def test_update_rejects_name_of_another_profile(store):
    store.create(profile("PC BNP"))
    other = store.create(profile("PC PERSO"))
    with pytest.raises(ProfileError):
        store.update(other["id"], {"name": "pc bnp"})
    assert store.update(other["id"], {"name": "PC PERSO"})["name"] == "PC PERSO"


def test_delete_active_clears_active(store):
    created = store.create(profile())
    store.set_active_id(created["id"])
    assert store.get_active_id() == created["id"]
    assert store.delete(created["id"]) is True
    assert store.get_active_id() is None
    assert store.delete(created["id"]) is False


def test_set_active_rejects_unknown_id(store):
    with pytest.raises(ProfileError):
        store.set_active_id(42)
    store.set_active_id(None)
    assert store.get_active_id() is None


def test_auto_receive_flag_persists_across_instances(tmp_path):
    first = ProfileStore(tmp_path / "profiles.sqlite3")
    assert first.get_auto_receive() is False
    first.set_auto_receive(True)
    assert ProfileStore(tmp_path / "profiles.sqlite3").get_auto_receive() is True


def test_matching_profile_ids_same_device_and_profile_only(store):
    bnp = store.create(profile("PC BNP"))
    perso = store.create(profile("PC PERSO"))
    store.create(profile("Laptop", device_name="Other card"))
    store.create(profile("4K", profile="quality"))
    time.sleep(0.01)
    newer = store.create(profile("PC JEU"))
    assert store.matching_profile_ids(bnp["id"]) == [newer["id"], perso["id"]]
    assert store.matching_profile_ids(9999) == []


def test_corrupt_database_does_not_raise(tmp_path):
    path = tmp_path / "profiles.sqlite3"
    path.write_bytes(b"this is not a sqlite database at all" * 20)
    broken = ProfileStore(path)
    assert broken.list() == []
    assert broken.get_auto_receive() is False
    assert broken.get_active_id() is None
