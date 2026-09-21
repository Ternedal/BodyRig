from __future__ import annotations

import hashlib
import json

import pytest

import bodyrig.photoreal_p3_quest2_final_manifest as final
from bodyrig.photoreal_p3_device_distillation_plan import (
    FIDELITY_DELTA_DIMENSIONS,
)
from bodyrig.photoreal_p3_device_distillation_runner import (
    _digest,
    _file_sha,
)
from bodyrig.photoreal_p3_quest2_final_manifest import (
    PhotorealP3Quest2FinalManifestError,
    materialize_final_distillation,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _profile() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-device-target-profile",
        "version": 1,
        "operator_supplied": True,
        "target_family": "meta-quest",
        "target_model": "quest-2",
        "target_runtime": "standalone",
        "target_refresh_hz": 72.0,
        "max_frame_time_ms": 13.888889,
        "stereo_rendering_required": True,
        "vr_safe_frame_pacing_required": True,
        "teacher_quality_ceiling_preserved": True,
        "fidelity_delta_reporting_required": True,
        "production_activation": False,
    }


def _request() -> dict[str, object]:
    profile = _profile()
    sources = [
        {
            "kind": "face-offset",
            "root_kind": "identity-export",
            "relative_path": "identity-export/face_offset.json",
            "size_bytes": 10,
            "sha256": "a" * 64,
        },
        {
            "kind": "joint-offset",
            "root_kind": "identity-export",
            "relative_path": "identity-export/joint_offset.json",
            "size_bytes": 10,
            "sha256": "b" * 64,
        },
        {
            "kind": "locator-offset",
            "root_kind": "identity-export",
            "relative_path": "identity-export/locator_offset.json",
            "size_bytes": 10,
            "sha256": "c" * 64,
        },
        {
            "kind": "shape-param",
            "root_kind": "identity-export",
            "relative_path": "identity-export/shape_param.json",
            "size_bytes": 10,
            "sha256": "d" * 64,
        },
        {
            "kind": "teacher-checkpoint",
            "root_kind": "teacher-output",
            "relative_path": "teacher-output/snapshot_4.pth",
            "size_bytes": 100,
            "sha256": "e" * 64,
        },
    ]
    result: dict[str, object] = {
        "format": "bodyrig-photoreal-p3-device-distillation-request",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_animated_human_review_sha256": "4" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "target_profile": profile,
        "target_profile_sha256": _digest(profile),
        "target_model": "quest-2",
        "adapter": "fixture-adapter",
        "adapter_revision": "6" * 64,
        "student_representation": "skinned-mesh-pbr",
        "student_components": [
            "specialized-eye-component",
            "teacher-derived-hair-component",
        ],
        "staged_teacher_sources": sources,
        "required_fidelity_delta_dimensions": list(
            FIDELITY_DELTA_DIMENSIONS
        ),
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "staged_teacher_only": True,
        "p3_distillation_execution_authorized": True,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_device_distillation_request_sha256"] = _digest(result)
    return result


def _measurements() -> list[dict[str, object]]:
    return [
        {
            "dimension": dimension,
            "metric": f"fixture-{dimension}-delta",
            "value": round(0.01 + index * 0.01, 6),
            "unit": "normalized-rmse",
            "teacher_reference": "sha256:" + "e" * 64 + "#teacher",
            "student_reference": "sha256:" + "f" * 64 + "#student",
        }
        for index, dimension in enumerate(FIDELITY_DELTA_DIMENSIONS)
    ]


def _authority(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    request = _request()
    (candidate / "request.json").write_text(
        json.dumps(request),
        encoding="utf-8",
    )

    hair_root = tmp_path / "hair"
    student = hair_root / "student"
    student.mkdir(parents=True)
    avatar = student / "avatar.vrm"
    basecolor = student / "basecolor.png"
    avatar.write_bytes(b"exact-final-vrm")
    basecolor.write_bytes(b"exact-final-basecolor")
    hair_receipt_path = hair_root / "p3-quest2-hair-student-receipt.json"
    hair_receipt_path.write_text("{}\n", encoding="utf-8")

    fidelity_path = tmp_path / "fidelity.json"
    fidelity_path.write_text("{}\n", encoding="utf-8")

    hair = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "p3_device_distillation_request_sha256": request[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_student_candidate_receipt_sha256": "7" * 64,
        "p3_quest2_eye_student_receipt_sha256": "8" * 64,
        "p3_quest2_hair_student_receipt_sha256": "9" * 64,
        "hair_runner_revision_sha256": "a" * 64,
        "hair_component_revision_sha256": "b" * 64,
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "implemented_student_components": [
            "specialized-eye-component",
            "teacher-derived-hair-component",
        ],
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.vrm",
                "size_bytes": avatar.stat().st_size,
                "sha256": _file_sha(avatar),
            },
            {
                "kind": "teacher-derived-basecolor",
                "relative_path": "student/basecolor.png",
                "size_bytes": basecolor.stat().st_size,
                "sha256": _file_sha(basecolor),
            },
        ],
    }
    fidelity = {
        "p3_device_distillation_request_sha256": request[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_fidelity_delta_evidence_sha256": "c" * 64,
        "teacher_checkpoint_sha256": "e" * 64,
    }
    return candidate, hair_root, fidelity_path, hair, fidelity


def test_final_request_requires_exact_digest() -> None:
    request = _request()
    validated = final._validate_request(request)
    assert validated["target_model"] == "quest-2"

    request["performer_id"] = "other"
    with pytest.raises(
        PhotorealP3Quest2FinalManifestError,
        match="digest mismatch",
    ):
        final._validate_request(request)


def test_final_manifest_materializes_core_valid_output(
    tmp_path,
    monkeypatch,
) -> None:
    (
        candidate,
        hair_root,
        fidelity_path,
        hair,
        fidelity,
    ) = _authority(tmp_path)
    monkeypatch.setattr(
        final,
        "validate_hair_student_receipt",
        lambda _value, *, hair_output_root: hair,
    )
    monkeypatch.setattr(
        final,
        "validate_fidelity_delta_evidence",
        lambda _value, *, hair_receipt, hair_output_root: fidelity,
    )
    monkeypatch.setattr(
        final,
        "canonical_manifest_measurements",
        lambda _value: _measurements(),
    )

    result = materialize_final_distillation(
        candidate_workspace=candidate,
        hair_output_root=hair_root,
        fidelity_evidence_path=fidelity_path,
        workspace=tmp_path / "final",
    )

    manifest = result["manifest"]
    receipt = result["execution_receipt"]
    provenance = result["provenance"]
    assert manifest["distillation_complete"] is True
    assert manifest["runtime_acceptance_authority"] is False
    assert manifest["photoreal_acceptance_authority"] is False
    assert manifest["production_activation"] is False
    assert len(manifest["student_artifacts"]) == 3
    assert receipt["artifact_bytes_verified_by_core"] is True
    assert receipt["human_runtime_visual_acceptance_required"] is True
    assert provenance["student_copy_byte_identical"] is True
    assert provenance["fidelity_delta_complete"] is True
    assert (tmp_path / "final" / "output" / "distillation-manifest.json").is_file()
    assert (
        tmp_path
        / "final"
        / "p3-device-distillation-execution-receipt.json"
    ).is_file()


def test_final_manifest_rejects_fidelity_for_other_request(
    tmp_path,
    monkeypatch,
) -> None:
    (
        candidate,
        hair_root,
        fidelity_path,
        hair,
        fidelity,
    ) = _authority(tmp_path)
    fidelity = dict(fidelity)
    fidelity["p3_device_distillation_request_sha256"] = "0" * 64
    monkeypatch.setattr(
        final,
        "validate_hair_student_receipt",
        lambda _value, *, hair_output_root: hair,
    )
    monkeypatch.setattr(
        final,
        "validate_fidelity_delta_evidence",
        lambda _value, *, hair_receipt, hair_output_root: fidelity,
    )

    with pytest.raises(
        PhotorealP3Quest2FinalManifestError,
        match="different request bytes",
    ):
        materialize_final_distillation(
            candidate_workspace=candidate,
            hair_output_root=hair_root,
            fidelity_evidence_path=fidelity_path,
            workspace=tmp_path / "final",
        )
