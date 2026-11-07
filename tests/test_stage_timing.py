from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import stage_timing
from bodyrig.stage_timing import ENVIRONMENT_VARIABLE, format_duration, main, parse_record, read_stage_timing, render_table


def _record(script: str, stage: str, started: str, finished: str, seconds: float, outcome: str = "pass") -> str:
    return json.dumps(
        {
            "format": "bodyrig-stage-timing",
            "version": 1,
            "script": script,
            "stage": stage,
            "started_utc": started,
            "finished_utc": finished,
            "duration_seconds": seconds,
            "outcome": outcome,
        }
    )


def _write_run(path: Path, *, bom: bool = False, extra_lines: tuple[str, ...] = ()) -> None:
    # The launcher wraps the pipeline, the pipeline wraps clone-body.ps1, and
    # clone-body.ps1 wraps its own stages: three nesting levels, written in
    # finish order (a wrapper appends after its children).
    lines = [
        _record("clone-body-from-stash-ready.ps1", "Live rig readiness", "2026-11-07T06:00:00Z", "2026-11-07T06:02:00Z", 120),
        _record("clone-body-from-stash.ps1", "Stash performer source selection", "2026-11-07T06:02:10Z", "2026-11-07T06:03:10Z", 60),
        _record("clone-body.ps1", "Recovery preflight", "2026-11-07T06:03:20Z", "2026-11-07T06:03:50Z", 30),
        _record("clone-body.ps1", "Video recovery", "2026-11-07T06:03:50Z", "2026-11-09T06:03:50Z", 172800),
        _record("clone-body.ps1", "Visual identity capture", "2026-11-09T06:03:50Z", "2026-11-09T07:03:50Z", 3600),
        _record("clone-body.ps1", "High-fidelity avatar fitting", "2026-11-09T07:04:00Z", "2026-11-10T07:04:00Z", 86400),
        _record("clone-body-from-stash.ps1", "BodyRig clone pipeline", "2026-11-07T06:03:15Z", "2026-11-10T07:04:05Z", 262850),
        _record("clone-body-from-stash-ready.ps1", "Stash clone pipeline", "2026-11-07T06:02:05Z", "2026-11-10T07:04:10Z", 262925),
    ]
    text = "\n".join(list(extra_lines[:1]) + lines + list(extra_lines[1:])) + "\n"
    if bom:
        text = "﻿" + text
    path.write_text(text, encoding="utf-8")


def test_summary_orders_stages_and_counts_only_leaf_stages(tmp_path: Path) -> None:
    sidecar = tmp_path / "session.timing.jsonl"
    _write_run(sidecar)
    summary = read_stage_timing(sidecar)
    assert summary["stage_count"] == 8
    assert summary["skipped_lines"] == 0
    assert summary["failed_stages"] == []
    assert [row["stage"] for row in summary["stages"]] == [
        "Live rig readiness",
        "Stash clone pipeline",
        "Stash performer source selection",
        "BodyRig clone pipeline",
        "Recovery preflight",
        "Video recovery",
        "Visual identity capture",
        "High-fidelity avatar fitting",
    ]
    # Wrappers (pipeline, launcher phase) are excluded; the leaf stages add up.
    assert summary["wall_clock_seconds"] == pytest.approx(120 + 60 + 30 + 172800 + 3600 + 86400)
    assert summary["started_utc"].isoformat() == "2026-11-07T06:00:00+00:00"
    assert summary["finished_utc"].isoformat() == "2026-11-10T07:04:10+00:00"


def test_unreadable_lines_are_counted_not_fatal(tmp_path: Path) -> None:
    sidecar = tmp_path / "session.timing.jsonl"
    bad = (
        "not json at all",
        json.dumps({"format": "bodyrig-stage-timing", "version": 2, "script": "x", "stage": "y", "started_utc": "2026-11-07T06:00:00Z", "finished_utc": "2026-11-07T06:00:01Z", "duration_seconds": 1, "outcome": "pass"}),
    )
    _write_run(sidecar, bom=True, extra_lines=bad)
    summary = read_stage_timing(sidecar)
    assert summary["stage_count"] == 8
    assert summary["skipped_lines"] == 2


def test_failed_stage_is_listed_and_rendered(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sidecar = tmp_path / "session.timing.jsonl"
    sidecar.write_text(
        _record("clone-body.ps1", "Recovery preflight", "2026-11-07T06:00:00Z", "2026-11-07T06:00:30Z", 30)
        + "\n"
        + _record("clone-body.ps1", "Video recovery", "2026-11-07T06:00:30Z", "2026-11-07T06:10:30Z", 600, outcome="fail")
        + "\n",
        encoding="utf-8",
    )
    summary = read_stage_timing(sidecar)
    assert summary["failed_stages"] == ["Video recovery"]
    table = render_table(summary)
    assert "Video recovery" in table and "fail" in table
    assert "Failed stages: Video recovery" in table
    assert main([str(sidecar)]) == 0
    out = capsys.readouterr().out
    assert "Wall clock (leaf stages): 10m 30s" in out
    assert main([str(sidecar), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed_stages"] == ["Video recovery"]
    assert payload["stages"][1]["started_utc"] == "2026-11-07T06:00:30Z"


def test_missing_sidecar_is_reported_not_raised_by_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "absent.timing.jsonl")]) == 1
    assert "not found" in capsys.readouterr().err
    with pytest.raises(FileNotFoundError):
        read_stage_timing(tmp_path / "absent.timing.jsonl")


@pytest.mark.parametrize(
    "mutation",
    [
        {"format": "other"},
        {"version": "1"},
        {"version": True},
        {"outcome": "ok"},
        {"started_utc": "2026-11-07 06:00:00"},  # no timezone
        {"finished_utc": "nope"},
        {"duration_seconds": "12"},
        {"duration_seconds": True},
        {"stage": "   "},
        {"script": 7},
    ],
)
def test_parse_record_rejects_shape_violations(mutation: dict) -> None:
    base = json.loads(_record("clone-body.ps1", "Video recovery", "2026-11-07T06:00:00Z", "2026-11-07T06:00:30Z", 30))
    assert parse_record(json.dumps(base)) is not None
    base.update(mutation)
    assert parse_record(json.dumps(base)) is None
    del base["stage"]
    assert parse_record(json.dumps(base)) is None
    assert parse_record("") is None
    assert parse_record("[1, 2]") is None


def test_format_duration_scales() -> None:
    assert format_duration(0.4) == "0.4s"
    assert format_duration(59) == "59.0s"
    assert format_duration(90) == "1m 30s"
    assert format_duration(3725) == "1h 02m 05s"
    assert format_duration(7 * 86400 + 3600 * 5 + 60 * 7) == "7d 05h 07m"


def test_environment_variable_name_is_the_one_the_scripts_use() -> None:
    assert ENVIRONMENT_VARIABLE == "BODYRIG_STAGE_TIMING_LOG"
    assert stage_timing.FORMAT == "bodyrig-stage-timing"
