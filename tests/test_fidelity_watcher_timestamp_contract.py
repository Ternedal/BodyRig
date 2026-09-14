from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHER = ROOT / "watch-fidelity-progress.ps1"
PRODUCER = ROOT / "run-profiled-fidelity-convergence.ps1"


def test_watcher_accepts_json_deserialized_datetime_objects_without_culture_roundtrip() -> None:
    source = WATCHER.read_text(encoding="utf-8")

    start = source.index("function Parse-Utc")
    end = source.index("$WorkRoot =", start)
    parse_utc = source[start:end]

    assert "param($Value)" in parse_utc
    assert "[DateTimeOffset]" in parse_utc
    assert "[DateTime]" in parse_utc
    assert "[DateTimeKind]::Unspecified" in parse_utc
    assert "[Globalization.CultureInfo]::InvariantCulture" in parse_utc
    assert "[Globalization.DateTimeStyles]::RoundtripKind" in parse_utc

    assert "$started = Parse-Utc $p.started_at" in source
    assert "$stageStarted = Parse-Utc $p.stage_started_at" in source
    assert "Parse-Utc ([string]$p.started_at)" not in source
    assert "Parse-Utc ([string]$p.stage_started_at)" not in source


def test_progress_producer_keeps_roundtrip_iso_timestamps() -> None:
    source = PRODUCER.read_text(encoding="utf-8")

    assert 'started_at = $runStart.ToString("o")' in source
    assert 'last_update = $now.ToString("o")' in source
    assert 'stage_started_at = $stageStart.ToString("o")' in source
