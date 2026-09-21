from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p3_quest_runtime_package as runtime
from bodyrig.photoreal_p3_quest_runtime_package import (
    PhotorealP3QuestRuntimePackageError,
    build_quest_runtime_package,
    validate_quest_runtime_package,
)
from bodyrig.photoreal_p3_device_distillation_runner import (
    REQUIRED_STUDENT_COMPONENTS,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    output = tmp_path / "student-output"
    avatar = output / "student" / "avatar.vrm"
    avatar.parent.mkdir(parents=True)
    avatar.write_bytes(b"synthetic-vrm")
    provenance = output / "student" / "exavatar-quest2-pbr-provenance.json"
    provenance_value: dict[str, object] = {
        "format": "bodyrig-exavatar-quest2-pbr-student-provenance",
        "version": 1,
        "adapter": "bodyrig-exavatar-quest2-pbr-v1",
        "adapter_revision": "a" * 64,
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    provenance_value["student_provenance_sha256"] = runtime._digest(
        provenance_value,
        omit="student_provenance_sha256",
    )
    provenance.write_text(
        json.dumps(provenance_value, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    execution: dict[str, object] = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "target_model": "quest-2",
        "adapter": "bodyrig-exavatar-quest2-pbr-v1",
        "adapter_revision": "a" * 64,
        "student_representation": "skinned-mesh-pbr",
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "p3_device_distillation_plan_sha256": "1" * 64,
        "p3_device_distillation_request_sha256": "2" * 64,
        "p3_device_distillation_execution_receipt_sha256": "3" * 64,
        "distillation_complete": True,
        "artifact_bytes_verified_by_core": True,
        "staged_teacher_only": True,
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "fidelity_delta_measurements": [
            {
                "dimension": "identity_likeness",
                "metric": "test",
                "value": 0.0,
                "unit": "delta",
                "teacher_reference": "teacher",
                "student_reference": "student",
            }
        ],
        "student_artifacts": [
            {
                "kind": "quest2-vrm-student-runtime",
                "relative_path": "student/avatar.vrm",
                "size_bytes": avatar.stat().st_size,
                "sha256": _sha(avatar.read_bytes()),
            },
            {
                "kind": "exavatar-quest2-pbr-provenance",
                "relative_path": "student/exavatar-quest2-pbr-provenance.json",
                "size_bytes": provenance.stat().st_size,
                "sha256": _sha(provenance.read_bytes()),
            },
        ],
    }
    return execution, output


def _trust(
    monkeypatch: pytest.MonkeyPatch,
    execution: dict[str, object],
) -> None:
    monkeypatch.setattr(
        runtime,
        "validate_execution_receipt",
        lambda value: execution,
    )


def test_runtime_package_matches_reference_renderer_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, source = _fixture(tmp_path)
    _trust(monkeypatch, execution)

    receipt = build_quest_runtime_package(
        execution,
        student_output_root=source,
        output_root=tmp_path / "runtime",
    )

    root = tmp_path / "runtime"
    manifest = json.loads((root / "runtime-manifest.json").read_text())
    assert manifest["format"] == "bodyrig-runtime-assets"
    assert manifest["version"] == 1
    assert manifest["avatar"] == "avatar.vrm"
    assert manifest["bodyprint"] == "bodyprint.json"
    assert manifest["payloads"] == ["avatar.vrm", "bodyprint.json"]
    assert manifest["avatar_sha256"] == _sha((root / "avatar.vrm").read_bytes())
    assert manifest["bodyprint_sha256"] == _sha((root / "bodyprint.json").read_bytes())
    assert receipt["runtime_loader_contract"] == "bodyrig-runtime-assets-v1"
    assert receipt["physical_device_review_required"] is True
    assert receipt["runtime_acceptance_authority"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_runtime_package_copies_exact_student_vrm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, source = _fixture(tmp_path)
    _trust(monkeypatch, execution)
    expected = (source / "student" / "avatar.vrm").read_bytes()

    build_quest_runtime_package(
        execution,
        student_output_root=source,
        output_root=tmp_path / "runtime",
    )

    assert (tmp_path / "runtime" / "avatar.vrm").read_bytes() == expected


def test_runtime_package_rejects_student_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, source = _fixture(tmp_path)
    _trust(monkeypatch, execution)
    (source / "student" / "avatar.vrm").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP3QuestRuntimePackageError,
        match="size/path drifted|bytes drifted",
    ):
        build_quest_runtime_package(
            execution,
            student_output_root=source,
            output_root=tmp_path / "runtime",
        )


def test_runtime_package_rejects_provenance_digest_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, source = _fixture(tmp_path)
    provenance = source / "student" / "exavatar-quest2-pbr-provenance.json"
    value = json.loads(provenance.read_text())
    value["target_model"] = "quest-3"
    provenance.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    execution["student_artifacts"][1]["size_bytes"] = provenance.stat().st_size
    execution["student_artifacts"][1]["sha256"] = _sha(provenance.read_bytes())
    _trust(monkeypatch, execution)

    with pytest.raises(
        PhotorealP3QuestRuntimePackageError,
        match="canonical Quest2 runtime semantics|digest mismatch",
    ):
        build_quest_runtime_package(
            execution,
            student_output_root=source,
            output_root=tmp_path / "runtime",
        )


def test_runtime_package_rejects_noncanonical_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, source = _fixture(tmp_path)
    execution["student_components"] = ["specialized-eye-component"]
    _trust(monkeypatch, execution)

    with pytest.raises(
        PhotorealP3QuestRuntimePackageError,
        match="canonical eye/hair components",
    ):
        build_quest_runtime_package(
            execution,
            student_output_root=source,
            output_root=tmp_path / "runtime",
        )


def test_runtime_package_readback_detects_avatar_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, source = _fixture(tmp_path)
    _trust(monkeypatch, execution)
    root = tmp_path / "runtime"
    build_quest_runtime_package(
        execution,
        student_output_root=source,
        output_root=root,
    )
    (root / "avatar.vrm").write_bytes(b"tampered")

    with pytest.raises(
        PhotorealP3QuestRuntimePackageError,
        match="payload bytes differ",
    ):
        validate_quest_runtime_package(root)


def test_runtime_package_readback_rejects_resealed_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    execution, source = _fixture(tmp_path)
    _trust(monkeypatch, execution)
    root = tmp_path / "runtime"
    build_quest_runtime_package(
        execution,
        student_output_root=source,
        output_root=root,
    )
    receipt_path = root / "p3-quest-runtime-package-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["photoreal_acceptance_authority"] = True
    receipt["p3_quest_runtime_package_receipt_sha256"] = runtime._digest(
        receipt,
        omit="p3_quest_runtime_package_receipt_sha256",
    )
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP3QuestRuntimePackageError,
        match="photoreal_acceptance_authority",
    ):
        validate_quest_runtime_package(root)
