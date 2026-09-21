from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import tools.photoreal_p3_exavatar_quest2_student_candidate as candidate
from tools.photoreal_p3_exavatar_quest2_student_candidate import (
    Quest2StudentCandidateError,
)


def _request() -> dict[str, object]:
    value: dict[str, object] = {
        "format": candidate.REQUEST_FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p3_device_distillation_plan_sha256": "2" * 64,
        "target_profile": {"target_model": "quest-2"},
        "adapter": "quest2-candidate",
        "adapter_revision": "a" * 64,
        "student_representation": "skinned-mesh-pbr",
        "student_components": [
            "specialized-eye-component",
            "teacher-derived-hair-component",
        ],
        "staged_teacher_sources": [],
        "staged_teacher_only": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p3_device_distillation_request_sha256"] = candidate._digest(value)
    return value


def _reseal(value: dict[str, object]) -> None:
    value["p3_device_distillation_request_sha256"] = candidate._digest(
        value,
        omit="p3_device_distillation_request_sha256",
    )


def test_validate_request_accepts_exact_quest2_candidate_binding() -> None:
    request = _request()

    candidate._validate_request(
        request,
        adapter="quest2-candidate",
        revision="a" * 64,
        representation="skinned-mesh-pbr",
        student_components=(
            "specialized-eye-component,"
            "teacher-derived-hair-component"
        ),
    )


def test_validate_request_rejects_resealed_runtime_authority() -> None:
    request = _request()
    request["runtime_acceptance_authority"] = True
    _reseal(request)

    with pytest.raises(
        Quest2StudentCandidateError,
        match="runtime_acceptance_authority",
    ):
        candidate._validate_request(
            request,
            adapter="quest2-candidate",
            revision="a" * 64,
            representation="skinned-mesh-pbr",
            student_components=(
                "specialized-eye-component,"
                "teacher-derived-hair-component"
            ),
        )


def test_validate_request_rejects_component_cli_drift() -> None:
    request = _request()

    with pytest.raises(
        Quest2StudentCandidateError,
        match="component CLI binding",
    ):
        candidate._validate_request(
            request,
            adapter="quest2-candidate",
            revision="a" * 64,
            representation="skinned-mesh-pbr",
            student_components="specialized-eye-component",
        )


def test_validate_request_rejects_digest_tamper() -> None:
    request = _request()
    request["performer_id"] = "different"

    with pytest.raises(
        Quest2StudentCandidateError,
        match="digest mismatch",
    ):
        candidate._validate_request(
            request,
            adapter="quest2-candidate",
            revision="a" * 64,
            representation="skinned-mesh-pbr",
            student_components=(
                "specialized-eye-component,"
                "teacher-derived-hair-component"
            ),
        )


def _write(root: Path, relative: str, payload: bytes) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "relative_path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _teacher_request(root: Path) -> dict[str, object]:
    records = []
    checkpoint = _write(
        root,
        "teacher-output/checkpoint/snapshot_4.pth",
        b"checkpoint",
    )
    records.append(
        {
            "kind": "teacher-checkpoint",
            "root_kind": "teacher-output",
            **checkpoint,
        }
    )
    for kind, filename, payload in (
        ("shape-param", "shape_param.json", b"shape"),
        ("face-offset", "face_offset.json", b"face"),
        ("joint-offset", "joint_offset.json", b"joint"),
        ("locator-offset", "locator_offset.json", b"locator"),
    ):
        record = _write(
            root,
            f"identity-export/identity/{filename}",
            payload,
        )
        records.append(
            {
                "kind": kind,
                "root_kind": "identity-export",
                **record,
            }
        )
    return {"staged_teacher_sources": records}


def test_verify_staged_teacher_requires_exact_five_source_files(
    tmp_path: Path,
) -> None:
    request = _teacher_request(tmp_path)

    result = candidate._verify_staged_teacher(request, tmp_path)

    assert set(result) == candidate.EXPECTED_SOURCE_KINDS


def test_verify_staged_teacher_rejects_extra_file(tmp_path: Path) -> None:
    request = _teacher_request(tmp_path)
    (tmp_path / "unexpected.bin").write_bytes(b"x")

    with pytest.raises(
        Quest2StudentCandidateError,
        match="filesystem universe differs",
    ):
        candidate._verify_staged_teacher(request, tmp_path)


def test_verify_staged_teacher_rejects_identity_root_substitution(
    tmp_path: Path,
) -> None:
    request = _teacher_request(tmp_path)
    request["staged_teacher_sources"][1]["root_kind"] = "teacher-output"

    with pytest.raises(
        Quest2StudentCandidateError,
        match="root-kind mismatch",
    ):
        candidate._verify_staged_teacher(request, tmp_path)
