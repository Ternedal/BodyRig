from __future__ import annotations

import json

import bodyrig.stash_cli as stash_cli


class _FakeClient:
    def __init__(self, config):
        self.config = config

    def version(self) -> str:
        return "v0.fixture"


def test_stash_health_probes_version_without_media_selection(monkeypatch, capsys):
    monkeypatch.setattr(stash_cli, "StashClient", _FakeClient)
    result = stash_cli.main(["health", "--url", "http://127.0.0.1:9999"])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "version": "v0.fixture"}
