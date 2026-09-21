from __future__ import annotations

import copy
import hashlib

import pytest

import bodyrig.photoreal_p3_quest2_review_runtime as review
from bodyrig.photoreal_p3_quest2_review_runtime import (
    PhotorealP3Quest2ReviewRuntimeError,
    materialize_review_runtime,
    validate_review_manifest,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _plan(tmp_path):
    output = tmp_path / "final-output"
    student = output / "student"
    student.mkdir(parents=True)
    payloads = {
        "student/avatar.vrm": b"exact-vrm",
        "student/basecolor.png": b"exact-basecolor",
        "student/quest2-modular-provenance.json": b'{"exact":"provenance"}\n',
    }
    kinds = {
        "student/avatar.vrm": "student-runtime-package",
        "student/basecolor.png": "teacher-derived-basecolor",
        "student/quest2-modular-provenance.json": "quest2-modular-provenance",
    }
    artifacts = []
    for relative, raw in payloads.items():
        path = output / relative
        path.write_bytes(raw)
        artifacts.append(
            {
                "kind": kinds[relative],
                "relative_path": relative,
                "size_bytes": len(raw),
                "sha256": _sha(raw),
            }
        )
    artifacts.sort(key=lambda item: item["relative_path"])
    plan = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "2" * 64,
        "p3_device_distillation_execution_receipt_sha256": "3" * 64,
        "p3_device_runtime_review_plan_sha256": "4" * 64,
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "student_components": [
            "specialized-eye-component",
            "teacher-derived-hair-component",
        ],
        "student_artifacts": artifacts,
        "runtime_review_ready": True,
        "physical_device_evidence_present": False,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    return plan, output


def _trust(monkeypatch: pytest.MonkeyPatch, plan: dict) -> None:
    monkeypatch.setattr(
        review,
        "validate_device_runtime_review_plan",
        lambda value: plan,
    )


def test_materialize_review_runtime_copies_exact_final_artifacts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, output = _plan(tmp_path)
    _trust(monkeypatch, plan)
    workspace = tmp_path / "review-runtime"

    result = materialize_review_runtime(
        plan,
        final_output_root=output,
        workspace=workspace,
        bodyrig_revision="a" * 40,
    )

    manifest = result["manifest"]
    receipt = result["receipt"]
    assert manifest["format"] == review.FORMAT
    assert manifest["avatar"] == "avatar.vrm"
    assert manifest["basecolor"] == "basecolor.png"
    assert manifest["provenance"] == "quest2-modular-provenance.json"
    assert manifest["physical_review_only"] is True
    assert manifest["comparison_only"] is True
    assert manifest["physical_device_evidence_present"] is False
    assert manifest["runtime_acceptance_authority"] is False
    assert manifest["photoreal_acceptance_authority"] is False
    assert manifest["production_activation"] is False
    assert receipt["artifact_bytes_verified_by_core"] is True
    assert (workspace / "p3-quest2-review-manifest.json").is_file()
    assert (workspace / "p3-quest2-review-runtime-receipt.json").is_file()

    reread = validate_review_manifest(manifest, workspace=workspace)
    assert reread["avatar_sha256"] == _sha(b"exact-vrm")


def test_review_runtime_rejects_source_artifact_tamper(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, output = _plan(tmp_path)
    _trust(monkeypatch, plan)
    (output / "student" / "avatar.vrm").write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP3Quest2ReviewRuntimeError,
        match="artifact bytes drifted",
    ):
        materialize_review_runtime(
            plan,
            final_output_root=output,
            workspace=tmp_path / "review-runtime",
            bodyrig_revision="a" * 40,
        )


def test_review_runtime_rejects_non_quest2_plan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, output = _plan(tmp_path)
    plan["target_device_model"] = "quest-3"
    _trust(monkeypatch, plan)

    with pytest.raises(
        PhotorealP3Quest2ReviewRuntimeError,
        match="crossed/failed review-only boundary",
    ):
        materialize_review_runtime(
            plan,
            final_output_root=output,
            workspace=tmp_path / "review-runtime",
            bodyrig_revision="a" * 40,
        )


def test_review_manifest_rejects_resealed_authority_escalation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, output = _plan(tmp_path)
    _trust(monkeypatch, plan)
    workspace = tmp_path / "review-runtime"
    result = materialize_review_runtime(
        plan,
        final_output_root=output,
        workspace=workspace,
        bodyrig_revision="a" * 40,
    )
    manifest = copy.deepcopy(result["manifest"])
    manifest["runtime_acceptance_authority"] = True

    with pytest.raises(
        PhotorealP3Quest2ReviewRuntimeError,
        match="boundary mismatch",
    ):
        validate_review_manifest(manifest, workspace=workspace)


def test_review_manifest_rejects_extra_workspace_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, output = _plan(tmp_path)
    _trust(monkeypatch, plan)
    workspace = tmp_path / "review-runtime"
    result = materialize_review_runtime(
        plan,
        final_output_root=output,
        workspace=workspace,
        bodyrig_revision="a" * 40,
    )
    (workspace / "unexpected.bin").write_bytes(b"x")

    with pytest.raises(
        PhotorealP3Quest2ReviewRuntimeError,
        match="file universe differs",
    ):
        validate_review_manifest(result["manifest"], workspace=workspace)


def test_review_manifest_rejects_boolean_version(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, output = _plan(tmp_path)
    _trust(monkeypatch, plan)
    workspace = tmp_path / "review-runtime"
    result = materialize_review_runtime(
        plan,
        final_output_root=output,
        workspace=workspace,
        bodyrig_revision="a" * 40,
    )
    manifest = copy.deepcopy(result["manifest"])
    manifest["version"] = True

    with pytest.raises(PhotorealP3Quest2ReviewRuntimeError):
        validate_review_manifest(manifest, workspace=workspace)
