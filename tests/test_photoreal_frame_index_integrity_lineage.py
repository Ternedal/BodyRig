from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_appearance_epoch_readback_authority as appearance_boundary
import bodyrig.photoreal_teacher_input_readback_authority as teacher_boundary
from bodyrig.photoreal_frame_index_integrity import (
    PhotorealFrameIndexIntegrityError,
    canonical_frame_index_sha256,
    seal_frame_index,
    validate_frame_index_integrity,
)


SOURCE_SHA = "a" * 64


def _observation(source_key: str, split: str) -> dict[str, object]:
    return {
        "source_key": source_key,
        "split": split,
        "eligible_for_teacher": True,
        "target_identity_verified": True,
    }


def _frame_index_core() -> dict[str, object]:
    observations = [
        _observation("scene:train:E:/train.mp4", "train"),
        _observation("scene:eval:E:/eval.mp4", "evaluation"),
    ]
    return {
        "format": "bodyrig-photoreal-frame-index",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "analyzer": "frame-test",
        "analyzer_revision": "r1",
        "analyzer_model_set_sha256": "b" * 64,
        "identity_bank_sha256": "c" * 64,
        "identity_calibration_sha256": "d" * 64,
        "identity_matching_calibrated": True,
        "identity_match_threshold": 0.8,
        "identity_authority_is_core_derived": True,
        "multi_candidate_identity_safe": True,
        "identity_ambiguous_sample_count": 0,
        "source_count": 2,
        "observed_source_count": 2,
        "observation_count": 2,
        "eligible_train_observation_count": 1,
        "eligible_evaluation_observation_count": 1,
        "perceptual_hash_algorithm_contract": "64-bit-hamming-v1",
        "cross_split_max_hamming_distance": 4,
        "cross_split_near_duplicate_count": 0,
        "cross_split_near_duplicates": [],
        "held_out_view_coverage_required": ["face-front"],
        "held_out_view_coverage_observed": ["face-front"],
        "held_out_view_coverage_missing": [],
        "rear_view_source_observable": False,
        "thresholds": {
            "minimum_face_visibility": 0.72,
            "minimum_full_body_visibility": 0.72,
            "minimum_sharpness": 0.35,
            "maximum_occlusion": 0.4,
        },
        "observations": observations,
        "teacher_training_authorized": True,
        "training_blockers": [],
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _sealed_frame_index() -> dict[str, object]:
    return seal_frame_index(_frame_index_core(), SOURCE_SHA)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_frame_index_seal_is_deterministic_and_lineage_bound() -> None:
    left = _sealed_frame_index()
    right = _sealed_frame_index()

    assert left["source_authorized_observations_sha256"] == SOURCE_SHA
    assert left["frame_index_sha256"] == right["frame_index_sha256"]
    assert validate_frame_index_integrity(left) == left["frame_index_sha256"]


def test_frame_index_nested_mutation_after_seal_fails_closed() -> None:
    sealed = _sealed_frame_index()
    tampered = copy.deepcopy(sealed)
    tampered["observations"][0]["target_identity_verified"] = False

    with pytest.raises(PhotorealFrameIndexIntegrityError, match="canonical digest mismatch"):
        validate_frame_index_integrity(tampered)


def test_frame_index_source_lineage_mutation_after_seal_fails_closed() -> None:
    sealed = _sealed_frame_index()
    sealed["source_authorized_observations_sha256"] = "f" * 64

    with pytest.raises(PhotorealFrameIndexIntegrityError, match="canonical digest mismatch"):
        validate_frame_index_integrity(sealed)


def test_frame_index_rejects_unexpected_field_even_after_reseal() -> None:
    sealed = _sealed_frame_index()
    sealed["teacher_override"] = True
    sealed["frame_index_sha256"] = canonical_frame_index_sha256(sealed)

    with pytest.raises(PhotorealFrameIndexIntegrityError, match="key set mismatch"):
        validate_frame_index_integrity(sealed)


def test_frame_index_rejects_boolean_version_before_sealing() -> None:
    core = _frame_index_core()
    core["version"] = True

    with pytest.raises(PhotorealFrameIndexIntegrityError, match="format/version mismatch"):
        seal_frame_index(core, SOURCE_SHA)


def test_appearance_boundary_binds_verified_frame_index_digest(tmp_path: Path, monkeypatch) -> None:
    frame_index_path = tmp_path / "frame-index.json"
    output_path = tmp_path / "appearance-plan.json"
    sealed = _sealed_frame_index()
    _write_json(frame_index_path, sealed)

    def fake_build(_frame_index):
        return {
            "format": "bodyrig-photoreal-appearance-epoch-plan",
            "version": 1,
            "appearance_epoch_plan_sha256": "0" * 64,
        }

    monkeypatch.setattr(appearance_boundary, "build_appearance_epoch_plan", fake_build)
    result = appearance_boundary.build_appearance_epoch_plan_file_strict(frame_index_path, output_path)

    assert result["source_frame_index_sha256"] == sealed["frame_index_sha256"]
    assert result["appearance_epoch_plan_sha256"] != "0" * 64
    assert json.loads(output_path.read_text(encoding="utf-8"))["source_frame_index_sha256"] == sealed["frame_index_sha256"]


def test_appearance_boundary_rejects_unsealed_frame_index_before_core(tmp_path: Path, monkeypatch) -> None:
    frame_index_path = tmp_path / "frame-index.json"
    output_path = tmp_path / "appearance-plan.json"
    _write_json(frame_index_path, _frame_index_core())

    def forbidden_build(_frame_index):
        raise AssertionError("appearance core must not run before frame-index integrity passes")

    monkeypatch.setattr(appearance_boundary, "build_appearance_epoch_plan", forbidden_build)
    with pytest.raises(appearance_boundary.PhotorealAppearanceEpochReadbackAuthorityError, match="key set mismatch"):
        appearance_boundary.build_appearance_epoch_plan_file_strict(frame_index_path, output_path)
    assert not output_path.exists()


def test_teacher_boundary_binds_verified_frame_index_digest(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "plan.json"
    receipt_path = tmp_path / "receipt.json"
    frame_index_path = tmp_path / "frame-index.json"
    selection_path = tmp_path / "selection.json"
    output_path = tmp_path / "teacher-input.json"
    for path in (plan_path, receipt_path, selection_path):
        _write_json(path, {})
    sealed = _sealed_frame_index()
    _write_json(frame_index_path, sealed)

    def fake_build(_plan, _receipt, _frame_index, _selection):
        return {
            "format": "bodyrig-photoreal-teacher-input",
            "version": 1,
            "teacher_input_sha256": "0" * 64,
        }

    monkeypatch.setattr(teacher_boundary, "build_teacher_input", fake_build)
    result = teacher_boundary.build_teacher_input_files_strict(
        plan_path,
        receipt_path,
        frame_index_path,
        selection_path,
        output_path,
    )

    assert result["source_frame_index_sha256"] == sealed["frame_index_sha256"]
    assert result["teacher_input_sha256"] != "0" * 64
    assert json.loads(output_path.read_text(encoding="utf-8"))["source_frame_index_sha256"] == sealed["frame_index_sha256"]


def test_teacher_boundary_rejects_unsealed_frame_index_before_core(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "plan.json"
    receipt_path = tmp_path / "receipt.json"
    frame_index_path = tmp_path / "frame-index.json"
    selection_path = tmp_path / "selection.json"
    output_path = tmp_path / "teacher-input.json"
    for path in (plan_path, receipt_path, selection_path):
        _write_json(path, {})
    _write_json(frame_index_path, _frame_index_core())

    def forbidden_build(*_args):
        raise AssertionError("teacher core must not run before frame-index integrity passes")

    monkeypatch.setattr(teacher_boundary, "build_teacher_input", forbidden_build)
    with pytest.raises(teacher_boundary.PhotorealTeacherInputReadbackAuthorityError, match="key set mismatch"):
        teacher_boundary.build_teacher_input_files_strict(
            plan_path,
            receipt_path,
            frame_index_path,
            selection_path,
            output_path,
        )
    assert not output_path.exists()
