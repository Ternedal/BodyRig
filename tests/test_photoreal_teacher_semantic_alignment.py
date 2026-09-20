from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

import bodyrig.photoreal_teacher_semantic_alignment as semantic_alignment
from bodyrig.photoreal_teacher_semantic_alignment import (
    PhotorealTeacherSemanticAlignmentError,
    REQUIRED_SEMANTIC_LABELS,
    build_semantic_alignment_handoff,
    record_semantic_alignment,
)


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_semantic_alignment_exavatar_adapter",
        ADAPTER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _teacher_fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    adapter = _load_adapter()
    output = tmp_path / "teacher"
    review = output / "review" / "neutral-pose"
    review.mkdir(parents=True)

    artifacts: list[dict[str, object]] = []
    for index in range(50):
        path = review / f"{index}.png"
        path.write_bytes(f"render-{index}".encode("ascii"))
        artifacts.append(
            {
                "kind": "neutral-pose-render",
                "relative_path": f"review/neutral-pose/{index}.png",
                "size_bytes": path.stat().st_size,
                "sha256": _sha(path),
            }
        )

    cameras = adapter._neutral_camera_manifest()
    camera_path = review / "cameras.json"
    camera_path.write_text(
        json.dumps(cameras, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts.append(
        {
            "kind": "neutral-pose-camera-manifest",
            "relative_path": "review/neutral-pose/cameras.json",
            "size_bytes": camera_path.stat().st_size,
            "sha256": _sha(camera_path),
        }
    )

    teacher_manifest = {
        "format": "bodyrig-photoreal-teacher-manifest",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "adapter": "bodyrig-exavatar-static-teacher-v1",
        "adapter_revision": "b" * 64,
        "upstream_repository": adapter.UPSTREAM_REPOSITORY,
        "upstream_commit": adapter.UPSTREAM_COMMIT,
        "training_complete": True,
        "consumed_training_source_keys": ["scene:t"],
        "consumed_training_observations": [],
        "artifacts": artifacts,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "production_activation": False,
    }
    (output / "teacher-manifest.json").write_text(
        json.dumps(teacher_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return teacher_manifest, output


def _mapping() -> dict[str, int]:
    return {
        "front": 25,
        "front-left-three-quarter": 31,
        "left-profile": 37,
        "rear": 0,
        "right-profile": 12,
        "front-right-three-quarter": 19,
    }


def test_handoff_binds_exact_camera_and_render_bytes_without_semantic_authority(tmp_path: Path) -> None:
    teacher, output = _teacher_fixture(tmp_path)

    handoff = build_semantic_alignment_handoff(teacher, output)

    assert handoff["view_count"] == 50
    assert handoff["required_semantic_labels"] == list(REQUIRED_SEMANTIC_LABELS)
    assert handoff["human_semantic_alignment_required"] is True
    assert handoff["human_semantic_alignment_complete"] is False
    assert handoff["semantic_camera_alignment_authority"] is False
    assert handoff["human_visual_likeness_acceptance"] is False
    assert handoff["photoreal_acceptance_authority"] is False
    assert handoff["production_activation"] is False

    view_25 = handoff["views"][25]
    render = output / view_25["render_relative_path"]
    assert view_25["render_sha256"] == _sha(render)
    assert view_25["normalized_azimuth_degrees"] == 0.0


def test_human_semantic_alignment_grants_orientation_authority_only(tmp_path: Path) -> None:
    teacher, output = _teacher_fixture(tmp_path)
    handoff = build_semantic_alignment_handoff(teacher, output)

    receipt = record_semantic_alignment(
        teacher,
        output,
        handoff,
        semantic_view_indices=_mapping(),
        reviewed_by="operator",
        review_notes="Reviewed all six orientations against the hash-bound neutral render orbit.",
        approve_human_review=True,
    )

    assert [item["semantic_label"] for item in receipt["alignments"]] == list(REQUIRED_SEMANTIC_LABELS)
    assert receipt["human_semantic_alignment_complete"] is True
    assert receipt["semantic_camera_alignment_authority"] is True
    assert receipt["human_visual_likeness_acceptance"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_semantic_alignment_requires_every_label(tmp_path: Path) -> None:
    teacher, output = _teacher_fixture(tmp_path)
    handoff = build_semantic_alignment_handoff(teacher, output)
    mapping = _mapping()
    mapping.pop("rear")

    with pytest.raises(PhotorealTeacherSemanticAlignmentError, match="every required label"):
        record_semantic_alignment(
            teacher,
            output,
            handoff,
            semantic_view_indices=mapping,
            reviewed_by="operator",
            review_notes="Incomplete on purpose.",
            approve_human_review=True,
        )


def test_semantic_alignment_rejects_duplicate_render_indices(tmp_path: Path) -> None:
    teacher, output = _teacher_fixture(tmp_path)
    handoff = build_semantic_alignment_handoff(teacher, output)
    mapping = _mapping()
    mapping["right-profile"] = mapping["left-profile"]

    with pytest.raises(PhotorealTeacherSemanticAlignmentError, match="unique render indices"):
        record_semantic_alignment(
            teacher,
            output,
            handoff,
            semantic_view_indices=mapping,
            reviewed_by="operator",
            review_notes="Duplicate view should fail closed.",
            approve_human_review=True,
        )


def test_semantic_alignment_rejects_tampered_handoff(tmp_path: Path) -> None:
    teacher, output = _teacher_fixture(tmp_path)
    handoff = build_semantic_alignment_handoff(teacher, output)
    tampered = copy.deepcopy(handoff)
    tampered["views"][25]["normalized_azimuth_degrees"] = 1.0

    with pytest.raises(PhotorealTeacherSemanticAlignmentError, match="not canonical"):
        record_semantic_alignment(
            teacher,
            output,
            tampered,
            semantic_view_indices=_mapping(),
            reviewed_by="operator",
            review_notes="Tampered handoff should fail closed.",
            approve_human_review=True,
        )


def test_handoff_rejects_resealed_machine_semantic_label(tmp_path: Path) -> None:
    teacher, output = _teacher_fixture(tmp_path)
    adapter = _load_adapter()
    camera_path = output / "review" / "neutral-pose" / "cameras.json"
    camera = json.loads(camera_path.read_text(encoding="utf-8"))
    camera["views"][25]["semantic_view_label"] = "front"
    camera["camera_manifest_sha256"] = adapter._digest(
        camera,
        omit="camera_manifest_sha256",
    )
    camera_path.write_text(
        json.dumps(camera, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for artifact in teacher["artifacts"]:
        if artifact["kind"] == "neutral-pose-camera-manifest":
            artifact["size_bytes"] = camera_path.stat().st_size
            artifact["sha256"] = _sha(camera_path)
            break

    with pytest.raises(PhotorealTeacherSemanticAlignmentError, match="machine semantic label"):
        build_semantic_alignment_handoff(teacher, output)


def test_handoff_rejects_tampered_render_bytes(tmp_path: Path) -> None:
    teacher, output = _teacher_fixture(tmp_path)
    (output / "review" / "neutral-pose" / "25.png").write_bytes(b"tampered")

    with pytest.raises(PhotorealTeacherSemanticAlignmentError, match="neutral render file SHA mismatch"):
        build_semantic_alignment_handoff(teacher, output)


def test_file_handoff_uses_runner_workspace_for_strict_readback_and_output_subdir_for_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "teacher-workspace"
    (workspace / "output").mkdir(parents=True)
    config = tmp_path / "config.json"
    teacher_input = tmp_path / "teacher-input.json"
    config.write_text("{}\n", encoding="utf-8")
    teacher_input.write_text("{}\n", encoding="utf-8")
    target = tmp_path / "semantic-handoff.json"
    captured: dict[str, object] = {}

    def fake_strict(config_path, teacher_input_path, workspace_path):
        captured["strict_workspace"] = Path(workspace_path).resolve()
        return {"sentinel": "validated"}

    def fake_build(validated, result_root):
        captured["validated"] = validated
        captured["result_root"] = Path(result_root).resolve()
        return {
            "format": "test-semantic-handoff",
            "semantic_alignment_handoff_sha256": "a" * 64,
        }

    monkeypatch.setattr(semantic_alignment, "validate_external_teacher_files_strict", fake_strict)
    monkeypatch.setattr(semantic_alignment, "build_semantic_alignment_handoff", fake_build)

    result = semantic_alignment.build_semantic_alignment_handoff_files(
        config,
        teacher_input,
        workspace,
        target,
    )

    assert result["format"] == "test-semantic-handoff"
    assert captured["strict_workspace"] == workspace.resolve()
    assert captured["result_root"] == (workspace / "output").resolve()
