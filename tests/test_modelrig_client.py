from __future__ import annotations

import json

import pytest

from bodyrig.modelrig_client import ModelRigClient, ModelRigClientError, ModelRigConfig


class _Response:
    def __init__(self, payload: dict):
        self.raw = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Length": str(len(self.raw))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, amount: int) -> bytes:
        return self.raw[:amount]


class _Opener:
    def __init__(self, payload: dict):
        self.payload = payload
        self.requests = []

    def open(self, request, timeout):  # type: ignore[no-untyped-def]
        self.requests.append((request, timeout))
        return _Response(self.payload)


def test_modelrig_url_must_be_loopback() -> None:
    with pytest.raises(ModelRigClientError, match="loopback"):
        ModelRigConfig(url="http://192.168.1.5:8080", token="abc")
    with pytest.raises(ModelRigClientError, match="credentials"):
        ModelRigConfig(url="http://user:pass@127.0.0.1:8080", token="abc")


def test_health_is_unauthed_and_identifies_modelrig() -> None:
    client = ModelRigClient(ModelRigConfig(token=""))
    opener = _Opener({"status": "ok", "service": "modelrig-server", "version": "1.2.3"})
    client._opener = opener
    value = client.health()
    assert value["service"] == "modelrig-server"
    request, timeout = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:8080/healthz"
    assert request.get_header("Authorization") is None
    assert timeout == 120


def test_protected_calls_require_token() -> None:
    client = ModelRigClient(ModelRigConfig(token=""))
    with pytest.raises(ModelRigClientError, match="MODELRIG_TOKEN"):
        client.models()


def test_chat_sends_exact_system_and_user_messages_without_global_mutation() -> None:
    client = ModelRigClient(ModelRigConfig(token="secret-token"))
    opener = _Opener({"message": {"role": "assistant", "content": "Et tørt svar."}, "done": True})
    client._opener = opener
    reply = client.chat(model="qwen3:8b", system="Du er Anna. Vær tør.", prompt="Hvordan går det?")
    assert reply == "Et tørt svar."
    request, _ = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:8080/api/v1/chat"
    assert request.get_header("Authorization") == "Bearer secret-token"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload == {
        "model": "qwen3:8b",
        "messages": [
            {"role": "system", "content": "Du er Anna. Vær tør."},
            {"role": "user", "content": "Hvordan går det?"},
        ],
        "stream": False,
    }


def test_models_returns_minimal_safe_surface() -> None:
    client = ModelRigClient(ModelRigConfig(token="secret-token"))
    opener = _Opener({"models": [{"name": "qwen3:8b", "size": 123}, {"model": "gemma3:4b"}, {"name": ""}]})
    client._opener = opener
    assert client.models() == [
        {"name": "qwen3:8b", "size": 123},
        {"name": "gemma3:4b", "size": None},
    ]
