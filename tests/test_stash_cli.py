from __future__ import annotations

import json
import subprocess

import pytest

import bodyrig.stash_cli as stash_cli
from bodyrig.stash_source import SourceCandidate, StashSourceError


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


def _candidate(path: str, *, scene_id: str = "scene-1") -> SourceCandidate:
    return SourceCandidate(
        scene_id=scene_id,
        scene_title=f"Fixture {scene_id}",
        path=path,
        width=1920,
        height=1080,
        duration=60.0,
        framerate=30.0,
        performer_count=1,
        score=100.0,
    )


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


def test_decode_gate_keeps_only_sources_that_ffmpeg_can_decode_one_video_frame(monkeypatch):
    candidates = [_candidate("C:/media/good.mp4"), _candidate("C:/media/bad.mp4", scene_id="scene-2")]
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        can_decode = any(str(argument).endswith("good.mp4") for argument in command)
        return subprocess.CompletedProcess(command, 0 if can_decode else 1)

    monkeypatch.setattr(stash_cli.subprocess, "run", fake_run)
    result = stash_cli._filter_decodable_sources(candidates, ffmpeg="C:/tools/ffmpeg.exe", timeout_seconds=20)

    assert result == [candidates[0]]
    assert len(calls) == 2
    first_command, first_kwargs = calls[0]
    assert first_command[0] == "C:/tools/ffmpeg.exe"
    assert "-nostdin" in first_command
    assert first_command[first_command.index("-frames:v") + 1] == "1"
    assert first_command[first_command.index("-map") + 1] == "0:v:0"
    assert candidates[0].path in first_command
    assert first_kwargs["shell"] is False
    assert first_kwargs["check"] is False
    assert first_kwargs["stdin"] is subprocess.DEVNULL
    assert first_kwargs["stdout"] is subprocess.DEVNULL


def test_decode_gate_skips_timeout_but_fails_closed_if_ffmpeg_cannot_start(monkeypatch):
    candidates = [_candidate("C:/media/slow.mp4"), _candidate("C:/media/good.mp4", scene_id="scene-2")]
    call_count = 0

    def timeout_then_success(command, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(stash_cli.subprocess, "run", timeout_then_success)
    assert stash_cli._filter_decodable_sources(candidates, ffmpeg="ffmpeg", timeout_seconds=5) == [candidates[1]]

    def cannot_start(command, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(stash_cli.subprocess, "run", cannot_start)
    with pytest.raises(StashSourceError, match="decode probe could not start"):
        stash_cli._filter_decodable_sources(candidates, ffmpeg="ffmpeg", timeout_seconds=5)


def test_stash_probe_proves_selected_performer_has_decodable_sources_without_emitting_paths(monkeypatch, capsys):
    ranked = [_candidate("C:/private/a.mp4"), _candidate("C:/private/b.mp4", scene_id="scene-2")]
    monkeypatch.setattr(stash_cli, "StashClient", _PerformerClient)
    monkeypatch.setattr(stash_cli, "rank_sources", lambda *args, **kwargs: ranked)
    monkeypatch.setattr(stash_cli, "_filter_decodable_sources", lambda *args, **kwargs: [ranked[0]])

    result = stash_cli.main(
        ["probe", "--performer-id", "7", "--url", "http://127.0.0.1:9999", "--ffmpeg", "fixture-ffmpeg"]
    )
    assert result == 0
    raw = capsys.readouterr().out
    payload = json.loads(raw)
    assert payload == {
        "ok": True,
        "version": "v0.fixture",
        "performer": {"id": "7", "name": "Alice", "disambiguation": "fixture"},
        "candidate_count": 2,
        "rankable_source_count": 2,
        "usable_source_count": 1,
        "decode_gate": "ffmpeg-one-frame-v1",
    }
    assert "C:/private" not in raw
    assert "path" not in raw.lower()


def test_stash_probe_fails_closed_when_selected_performer_has_no_rankable_local_sources(monkeypatch, capsys):
    monkeypatch.setattr(stash_cli, "StashClient", _PerformerClient)
    monkeypatch.setattr(stash_cli, "rank_sources", lambda *args, **kwargs: [])

    result = stash_cli.main(
        ["probe", "--performer-id", "7", "--url", "http://127.0.0.1:9999"]
    )
    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no rankable local video sources" in captured.err


def test_stash_probe_fails_closed_when_rankable_sources_do_not_decode(monkeypatch, capsys):
    ranked = [_candidate("C:/private/broken.mp4")]
    monkeypatch.setattr(stash_cli, "StashClient", _PerformerClient)
    monkeypatch.setattr(stash_cli, "rank_sources", lambda *args, **kwargs: ranked)
    monkeypatch.setattr(stash_cli, "_filter_decodable_sources", lambda *args, **kwargs: [])

    result = stash_cli.main(
        ["probe", "--performer-id", "7", "--url", "http://127.0.0.1:9999"]
    )
    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no locally decodable video sources" in captured.err
    assert "broken.mp4" not in captured.err


def test_stash_select_uses_decode_gate_by_default_and_skip_is_diagnostics_only(monkeypatch, capsys, tmp_path):
    ranked = [_candidate("C:/private/a.mp4")]
    calls = []
    monkeypatch.setattr(stash_cli, "StashClient", _PerformerClient)
    monkeypatch.setattr(stash_cli, "rank_sources", lambda *args, **kwargs: ranked)

    def decode(candidates, **kwargs):
        calls.append(kwargs)
        return list(candidates)

    monkeypatch.setattr(stash_cli, "_filter_decodable_sources", decode)

    first = tmp_path / "first.json"
    result = stash_cli.main(
        ["select", "--performer-id", "7", "--out", str(first), "--url", "http://127.0.0.1:9999", "--ffmpeg", "fixture-ffmpeg"]
    )
    assert result == 0
    assert calls == [{"ffmpeg": "fixture-ffmpeg", "timeout_seconds": 20}]

    calls.clear()
    second = tmp_path / "second.json"
    result = stash_cli.main(
        ["select", "--performer-id", "7", "--out", str(second), "--url", "http://127.0.0.1:9999", "--skip-decode-probe"]
    )
    assert result == 0
    assert calls == []
    capsys.readouterr()
