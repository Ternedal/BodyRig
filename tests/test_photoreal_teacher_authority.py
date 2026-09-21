from __future__ import annotations

import copy
import hashlib
import json

import pytest

import bodyrig.photoreal_teacher_authority as teacher_authority
from bodyrig.photoreal_teacher_authority import (
    validate_teacher_input_document,
    validate_teacher_input_upstream_versions,
)
from bodyrig.photoreal_teacher_input import PhotorealTeacherInputError
from bodyrig.photoreal_teacher_runner import PhotorealTeacherRunnerError


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source(*, key: str, group: str, path: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "kind": "video",
        "resolved_path": path,
        "size_bytes": 123456,
        "sha256": sha * 64,
        "information_score": 100.0,
        "width": 3840,
        "height": 2160,
        "projection": "flat",
        "stereo_layout": "mono",
    }


def _observation(*, key: str, group: str, split: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "split": split,
        "frame_sha256": sha * 64,
        "timestamp_seconds": 1.25,
        "eye": "mono",
        "view_bin": "front",
        "coverage": ["face-front", "full-body-front"],
    }


def _teacher_input(*, version: int | float = 1) -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-input",
        "version": version,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "selected_epoch_id": "epoch-a",
        "appearance_epoch_selection_sha256": "a" * 64,
        "identity_bank_sha256": "b" * 64,
        "identity_calibration_sha256": "c" * 64,
        "analyzer_model_set_sha256": "d" * 64,
        "training_sources": [
            _source(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                path=r"\\stash\VR_E\train.mp4",
                sha="e",
            )
        ],
        "held_out_evaluation_sources": [
            _source(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                path=r"\\stash\VR_E\eval.mp4",
                sha="f",
            )
        ],
        "training_observations": [
            _observation(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                split="train",
                sha="1",
            )
        ],
        "held_out_evaluation_observations": [
            _observation(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                split="evaluation",
                sha="2",
            )
        ],
        "held_out_view_coverage_required": ["face-front", "full-body-front"],
        "held_out_view_coverage_observed": ["face-front", "full-body-front"],
        "held_out_view_coverage_missing": [],
        "training_source_count": 1,
        "held_out_evaluation_source_count": 1,
        "training_observation_count": 1,
        "held_out_evaluation_observation_count": 1,
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["teacher_input_sha256"] = _digest(value)
    return value


def _reseal(value: dict[str, object]) -> None:
    value.pop("teacher_input_sha256", None)
    value["teacher_input_sha256"] = _digest(value)


def test_teacher_input_authority_accepts_exact_numeric_v1_manifest() -> None:
    value = _teacher_input()

    result = validate_teacher_input_document(value)

    assert result["teacher_input_sha256"] == value["teacher_input_sha256"]
    assert result["teacher_training_authorized"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_teacher_input_authority_preserves_numeric_1_0_compatibility() -> None:
    value = _teacher_input(version=1.0)

    result = validate_teacher_input_document(value)

    assert result["version"] == 1.0


def test_teacher_input_authority_rejects_boolean_v1_even_when_resealed() -> None:
    value = _teacher_input()
    value["version"] = True
    _reseal(value)

    with pytest.raises(PhotorealTeacherRunnerError, match="format/version mismatch"):
        validate_teacher_input_document(value)


def test_teacher_input_authority_rejects_content_tamper_with_stale_digest() -> None:
    value = _teacher_input()
    value["training_sources"][0]["resolved_path"] = r"\\stash\VR_E\substituted.mp4"

    with pytest.raises(PhotorealTeacherRunnerError, match="SHA-256 does not match manifest content"):
        validate_teacher_input_document(value)


def test_teacher_input_authority_rejects_nested_extension_even_when_resealed() -> None:
    value = _teacher_input()
    value["training_observations"][0]["teacher_override"] = True
    _reseal(value)

    with pytest.raises(PhotorealTeacherRunnerError, match="fields must match v1 exactly"):
        validate_teacher_input_document(value)


def test_teacher_input_authority_rejects_train_eval_group_overlap_even_when_resealed() -> None:
    value = _teacher_input()
    value["held_out_evaluation_sources"][0]["group_id"] = "scene:train"
    value["held_out_evaluation_observations"][0]["group_id"] = "scene:train"
    _reseal(value)

    with pytest.raises(PhotorealTeacherRunnerError, match="source groups overlap"):
        validate_teacher_input_document(value)


@pytest.mark.parametrize("boundary", ["plan", "receipt", "frame_index", "selection"])
def test_teacher_input_upstream_versions_reject_boolean_v1(boundary: str) -> None:
    plan = {"format": "bodyrig-photoreal-dataset-plan", "version": 1}
    receipt = {"format": "bodyrig-photoreal-source-receipt", "version": 1}
    frame_index = {"format": "bodyrig-photoreal-frame-index", "version": 1}
    selection = {"format": "bodyrig-photoreal-appearance-epoch-selection", "version": 1}
    values = {
        "plan": plan,
        "receipt": receipt,
        "frame_index": frame_index,
        "selection": selection,
    }
    values[boundary]["version"] = True

    with pytest.raises(PhotorealTeacherInputError, match="format/version mismatch"):
        validate_teacher_input_upstream_versions(plan, receipt, frame_index, selection)


def test_teacher_input_upstream_versions_accept_numeric_1_0() -> None:
    validate_teacher_input_upstream_versions(
        {"format": "bodyrig-photoreal-dataset-plan", "version": 1.0},
        {"format": "bodyrig-photoreal-source-receipt", "version": 1.0},
        {"format": "bodyrig-photoreal-frame-index", "version": 1.0},
        {"format": "bodyrig-photoreal-appearance-epoch-selection", "version": 1.0},
    )


def test_strict_teacher_reuse_reads_runner_output_subdirectory(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    input_path = tmp_path / "teacher-input.json"
    workspace = tmp_path / "teacher-workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    config_path.write_text("{}\n", encoding="utf-8")
    input_path.write_text("{}\n", encoding="utf-8")
    (output / "teacher-manifest.json").write_text(
        json.dumps({"sentinel": "manifest"}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(teacher_authority, "load_teacher_config", lambda _path: {"sentinel": "config"})
    monkeypatch.setattr(
        teacher_authority,
        "validate_teacher_input_document",
        lambda value: {"validated": value},
    )
    monkeypatch.setattr(
        teacher_authority,
        "build_teacher_request",
        lambda config, validated: {"config": config, "validated": validated},
    )
    captured: dict[str, object] = {}

    def fake_validate(manifest, *, request, output_dir):
        captured["manifest"] = manifest
        captured["request"] = request
        captured["output_dir"] = output_dir
        return {"status": "validated"}

    monkeypatch.setattr(teacher_authority, "validate_teacher_result", fake_validate)

    result = teacher_authority.validate_external_teacher_files_strict(
        config_path,
        input_path,
        workspace,
    )

    assert result == {"status": "validated"}
    assert captured["manifest"] == {"sentinel": "manifest"}
    assert captured["output_dir"] == output.resolve()


def test_strict_teacher_reuse_rejects_workspace_without_runner_output(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    input_path = tmp_path / "teacher-input.json"
    workspace = tmp_path / "teacher-workspace"
    workspace.mkdir()
    config_path.write_text("{}\n", encoding="utf-8")
    input_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(teacher_authority, "load_teacher_config", lambda _path: {})
    monkeypatch.setattr(teacher_authority, "validate_teacher_input_document", lambda value: value)
    monkeypatch.setattr(teacher_authority, "build_teacher_request", lambda _config, _input: {})

    with pytest.raises(PhotorealTeacherRunnerError, match="teacher output directory is missing"):
        teacher_authority.validate_external_teacher_files_strict(
            config_path,
            input_path,
            workspace,
        )
