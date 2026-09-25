from __future__ import annotations

import json
import os
from pathlib import Path

from bodyrig import photoreal_control_plane_ui as control


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run(root: Path, name: str, performer_id: str, stamp: int) -> Path:
    run = root / "photoreal-v2" / "overnight" / name
    run.mkdir(parents=True)
    _write_json(run / "source-resume-receipt.json", {"performer_id": performer_id})
    os.utime(run, (stamp, stamp))
    return run


def test_photoreal_history_marks_only_latest_valid_run_as_continuation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    older = _run(
        tmp_path,
        "performer-42-20260920-100000-resume1",
        "42",
        1000,
    )
    newer = _run(
        tmp_path,
        "performer-42-20260920-110000-resume2",
        "42",
        2000,
    )
    _run(
        tmp_path,
        "performer-42-20260920-120000-resume3",
        "99",
        3000,
    )

    _write_json(
        newer / "identity-calibration.json",
        {
            "format": "bodyrig-photoreal-identity-calibration",
            "version": 1,
            "target_performer_id": "42",
            "identity_matching_authorized": True,
        },
    )
    teacher = Path(str(newer.resolve()) + "-teacher")
    teacher.mkdir()
    _write_json(
        teacher / "teacher-input.json",
        {
            "format": "bodyrig-photoreal-teacher-input",
            "version": 1,
            "performer_id": "42",
            "teacher_input_sha256": "a" * 64,
        },
    )
    _write_json(teacher / "exavatar-teacher-config.json", {"command": []})
    _write_json(
        teacher / "exavatar-teacher-output" / "output" / "teacher-manifest.json",
        {"ok": True},
    )

    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    history = control._photoreal_run_history("42", newer, limit=8)

    assert [item["path"] for item in history] == [str(newer.resolve()), str(older.resolve())]
    assert history[0]["current"] is True
    assert history[0]["continuation_candidate"] is True
    assert history[0]["role"] == "current-canonical-run"
    assert history[0]["calibration_state"] == "valid"
    assert history[0]["identity_matching_authorized"] is True
    assert history[0]["teacher_input_valid"] is True
    assert history[0]["teacher_input_sha256"] == "a" * 64
    assert history[0]["teacher_config_present"] is True
    assert history[0]["teacher_manifest_present"] is True
    assert history[0]["authority"]["historical_execution_authority"] is False

    assert history[1]["current"] is False
    assert history[1]["continuation_candidate"] is False
    assert history[1]["role"] == "history-only"
    assert history[1]["authority"]["continuation_candidate"] is False


def test_photoreal_history_rejects_semantically_wrong_teacher_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run = _run(
        tmp_path,
        "performer-42-20260920-130000-resume4",
        "42",
        4000,
    )
    teacher = Path(str(run.resolve()) + "-teacher")
    teacher.mkdir()
    _write_json(
        teacher / "teacher-input.json",
        {
            "format": "bodyrig-photoreal-teacher-input",
            "version": 1,
            "performer_id": "99",
            "teacher_input_sha256": "b" * 64,
        },
    )

    monkeypatch.setattr(control, "data_dir", lambda: tmp_path)
    history = control._photoreal_run_history("42", run)

    assert len(history) == 1
    assert history[0]["teacher_input_present"] is True
    assert history[0]["teacher_input_valid"] is False
    assert history[0]["teacher_input_sha256"] is None
