from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p1_exavatar_lineage as lineage


def test_p1_exavatar_lineage_binds_launch_and_p1_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher = tmp_path / "teacher"
    p1_root = teacher / "p1-static-teacher-review"
    p1_root.mkdir(parents=True)
    receipt_path = p1_root / "p1-likeness-review.json"
    receipt_path.write_text('{"receipt":"bytes"}\n', encoding="utf-8")

    launch = {
        "run_id": "20260928-120000-" + ("a" * 32),
        "bodyrig_revision": "b" * 40,
        "launch_authority_sha256": "c" * 64,
        "teacher_manifest_sha256": "d" * 64,
    }
    manifest = {"p1_likeness_review_manifest_sha256": "e" * 64}
    receipt = {
        "p1_likeness_review_sha256": "f" * 64,
        "p1_static_teacher_status": "pass",
        "p2_animation_authorized": True,
    }

    monkeypatch.setattr(
        lineage,
        "_current",
        lambda teacher_root: (receipt_path, launch, manifest, receipt),
    )

    recorded = lineage.build_p1_exavatar_lineage(teacher)
    assert recorded["launch_authority_sha256"] == "c" * 64
    assert recorded["teacher_manifest_sha256"] == "d" * 64
    assert recorded["p1_likeness_review_sha256"] == "f" * 64
    assert recorded["p2_animation_authorized"] is True
    assert recorded["photoreal_acceptance_authority"] is False
    assert recorded["production_activation"] is False
    assert len(recorded["p1_exavatar_lineage_sha256"]) == 64

    validated = lineage.validate_p1_exavatar_lineage(teacher)
    assert validated["p1_exavatar_lineage_sha256"] == recorded["p1_exavatar_lineage_sha256"]


def test_p1_exavatar_lineage_rejects_tampered_launch_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    teacher = tmp_path / "teacher"
    p1_root = teacher / "p1-static-teacher-review"
    p1_root.mkdir(parents=True)
    receipt_path = p1_root / "p1-likeness-review.json"
    receipt_path.write_text('{"receipt":"bytes"}\n', encoding="utf-8")

    launch = {
        "run_id": "20260928-120000-" + ("a" * 32),
        "bodyrig_revision": "b" * 40,
        "launch_authority_sha256": "c" * 64,
        "teacher_manifest_sha256": "d" * 64,
    }
    manifest = {"p1_likeness_review_manifest_sha256": "e" * 64}
    receipt = {
        "p1_likeness_review_sha256": "f" * 64,
        "p1_static_teacher_status": "pass",
        "p2_animation_authorized": True,
    }
    monkeypatch.setattr(
        lineage,
        "_current",
        lambda teacher_root: (receipt_path, launch, manifest, receipt),
    )
    lineage.build_p1_exavatar_lineage(teacher)

    path = p1_root / "exavatar-lineage.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["launch_authority_sha256"] = "0" * 64
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    with pytest.raises(lineage.PhotorealP1ExAvatarLineageError, match="launch_authority_sha256"):
        lineage.validate_p1_exavatar_lineage(teacher)
