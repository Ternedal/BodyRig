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


class _PerformerClient(_FakeClient):
    def performer(self, performer_id: str):
        return {"id": performer_id, "name": "Alice", "disambiguation": "fixture"}

    def scenes_for_performer(self, performer_id: str, *, limit: int = 200):
        return [{"id": "scene-1"}, {"id": "scene-2"}]


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


def test_stash_probe_proves_selected_performer_has_usable_sources_without_emitting_paths(monkeypatch, capsys):
    monkeypatch.setattr(stash_cli, "StashClient", _PerformerClient)
    monkeypatch.setattr(stash_cli, "rank_sources", lambda *args, **kwargs: [object(), object()])

    result = stash_cli.main(
        ["probe", "--performer-id", "7", "--url", "http://127.0.0.1:9999"]
    )
    assert result == 0
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert payload == {
        "ok": True,
        "version": "v0.fixture",
        "performer": {"id": "7", "name": "Alice", "disambiguation": "fixture"},
        "candidate_count": 2,
        "usable_source_count": 2,
    }
    assert "path" not in raw.lower()


def test_stash_probe_fails_closed_when_selected_performer_has_no_usable_local_sources(monkeypatch, capsys):
    monkeypatch.setattr(stash_cli, "StashClient", _PerformerClient)
    monkeypatch.setattr(stash_cli, "rank_sources", lambda *args, **kwargs: [])

    result = stash_cli.main(
        ["probe", "--performer-id", "7", "--url", "http://127.0.0.1:9999"]
    )
    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no usable local video sources" in captured.err
