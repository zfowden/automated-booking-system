import sys
import types

import pytest

from tennis_booking import secrets as secrets_mod


def _install_fake_secretmanager(monkeypatch, store):
    """Install a fake google.cloud.secretmanager whose client reads from `store`."""
    fake_google = types.ModuleType("google")
    fake_cloud = types.ModuleType("google.cloud")
    fake_sm = types.ModuleType("google.cloud.secretmanager")

    class FakePayload:
        def __init__(self, data):
            self.data = data

    class FakeResponse:
        def __init__(self, data):
            self.payload = FakePayload(data)

    class FakeClient:
        def access_secret_version(self, request):
            name = request["name"]
            secret_id = name.split("/secrets/")[1].split("/versions/")[0]
            if secret_id not in store:
                raise KeyError(f"no such secret {secret_id}")
            return FakeResponse(store[secret_id].encode("utf-8"))

    fake_sm.SecretManagerServiceClient = FakeClient
    fake_cloud.secretmanager = fake_sm
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.secretmanager", fake_sm)


def test_load_secrets_into_env(monkeypatch):
    store = {"CLUBSPARK_PASSWORD": "hunter2", "SENDGRID_API_KEY": "SG.key"}
    _install_fake_secretmanager(monkeypatch, store)
    for name in secrets_mod.SECRET_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    loaded = secrets_mod.load_secrets_into_env("proj", names=tuple(store))
    assert set(loaded) == set(store)
    import os
    assert os.environ["CLUBSPARK_PASSWORD"] == "hunter2"
    assert os.environ["SENDGRID_API_KEY"] == "SG.key"


def test_missing_secret_is_skipped(monkeypatch):
    _install_fake_secretmanager(monkeypatch, {"CARD_NUMBER": "4111"})
    monkeypatch.delenv("CARD_NUMBER", raising=False)
    monkeypatch.delenv("CARD_CVV", raising=False)
    # CARD_CVV doesn't exist in the store -> skipped, no crash.
    loaded = secrets_mod.load_secrets_into_env("proj", names=("CARD_NUMBER", "CARD_CVV"))
    assert loaded == ["CARD_NUMBER"]


def test_existing_env_not_overwritten(monkeypatch):
    _install_fake_secretmanager(monkeypatch, {"CARD_CVV": "999"})
    monkeypatch.setenv("CARD_CVV", "already-set")
    loaded = secrets_mod.load_secrets_into_env("proj", names=("CARD_CVV",))
    assert loaded == []  # skipped because already present
    import os
    assert os.environ["CARD_CVV"] == "already-set"


def test_no_project_raises(monkeypatch):
    with pytest.raises(ValueError):
        secrets_mod.load_secrets_into_env("")
