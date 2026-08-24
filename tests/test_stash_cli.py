from __future__ import annotations

import json

import bodyrig.stash_cli as stash_cli
from bodyrig.stash_source import StashSourceError


class _FakeClient:
    def __init__(self, config):
        self.config = config
        self.probes: list[tuple[str, int]] = []

    def version(self) -> str:
        return "v0.fixture"

    def search_performers(self, term: str, *, limit: int = 25):
        self.probes.append((term, limit))
        return []


class _ReadDeniedClient(_FakeClient):
    def search_performers(self, term: str, *, limit: int = 25):
        raise StashSourceError("performer read denied")


def test_stash_health_probes_version_and_performer_read_without_media_selection(monkeypatch, capsys):
    holder = {}

    class _Client(_FakeClient):
        def __init__(self, config):
            super().__init__(config)
            holder["client"] = self

    monkeypatch.setattr(stash_cli, "StashClient", _Client)
    result = stash_cli.main(["health", "--url", "http://127.0.0.1:9999"])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "version": "v0.fixture", "performer_read": True}
    assert holder["client"].probes == [(stash_cli._HEALTH_PROBE_TERM, 1)]


def test_stash_health_fails_when_performer_read_capability_is_denied(monkeypatch, capsys):
    monkeypatch.setattr(stash_cli, "StashClient", _ReadDeniedClient)
    result = stash_cli.main(["health", "--url", "http://127.0.0.1:9999"])
    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "performer read denied" in captured.err
