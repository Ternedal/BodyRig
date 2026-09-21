from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_p1_likeness_review import (
    PhotorealP1LikenessReviewError,
    build_likeness_review_pack,
    record_likeness_review,
    validate_likeness_review_pack,
    validate_likeness_review_receipt,
)


def _digest(value: dict[str, object], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    teacher = tmp_path / "teacher"
    reference = tmp_path / "appearance"
    (teacher / "review" / "neutral-pose").mkdir(parents=True)
    (reference / "frames").mkdir(parents=True)

    teacher_png = teacher / "review" / "neutral-pose" / "25.png"
    reference_png = reference / "frames" / "eval.png"
    teacher_png.write_bytes(b"teacher-render")
    reference_png.write_bytes(b"held-out-reference")
    return teacher, reference


def _pairing(teacher: Path, reference: Path) -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-p1-heldout-pairing",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "semantic_alignment_sha256": "b" * 64,
        "p1_pairing_handoff_sha256": "c" * 64,
        "pairs": [
            {
                "criterion": "face-front",
                "teacher_semantic_label": "front",
                "teacher_render_index": 25,
                "teacher_render_relative_path": "review/neutral-pose/25.png",
                "teacher_render_sha256": _sha(teacher / "review" / "neutral-pose" / "25.png"),
                "held_out_frame_id": "review-frame-eval",
                "held_out_group_id": "scene:eval",
                "held_out_source_ref": "d" * 20,
                "held_out_frame_sha256": "e" * 64,
                "held_out_view_bin": "front",
                "held_out_review_relative_path": "frames/eval.png",
                "held_out_review_png_sha256": _sha(reference / "frames" / "eval.png"),
            },
            {
                "criterion": "full-body-front",
                "teacher_semantic_label": "front",
                "teacher_render_index": 25,
                "teacher_render_relative_path": "review/neutral-pose/25.png",
                "teacher_render_sha256": _sha(teacher / "review" / "neutral-pose" / "25.png"),
                "held_out_frame_id": "review-frame-eval",
                "held_out_group_id": "scene:eval",
                "held_out_source_ref": "d" * 20,
                "held_out_frame_sha256": "e" * 64,
                "held_out_view_bin": "front",
                "held_out_review_relative_path": "frames/eval.png",
                "held_out_review_png_sha256": _sha(reference / "frames" / "eval.png"),
            },
        ],
        "reviewed_by": "operator",
        "review_notes": "Pairing reviewed; likeness not judged.",
        "human_pairing_required": True,
        "human_pairing_complete": True,
        "held_out_pairing_authority": True,
        "human_visual_likeness_acceptance": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p1_pairing_sha256"] = _digest(value)
    return value


def test_review_pack_copies_only_hash_bound_teacher_and_held_out_bytes(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    output = tmp_path / "p1-review"

    manifest = build_likeness_review_pack(
        pairing,
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=output,
    )

    assert manifest["criterion_count"] == 2
    assert manifest["human_visual_review_required"] is True
    assert manifest["human_visual_review_complete"] is False
    assert manifest["p1_static_teacher_acceptance_authority"] is False
    assert manifest["human_visual_likeness_acceptance"] is False
    assert manifest["p2_animation_authorized"] is False
    assert manifest["photoreal_acceptance_authority"] is False
    assert manifest["production_activation"] is False

    for pair in manifest["pairs"]:
        assert _sha(output / pair["teacher_copy_relative_path"]) == pair["teacher_copy_sha256"]
        assert _sha(output / pair["reference_copy_relative_path"]) == pair["reference_copy_sha256"]


def test_all_pass_grants_only_p1_and_p2_authority(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    output = tmp_path / "p1-review"
    manifest = build_likeness_review_pack(
        pairing,
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=output,
    )

    receipt = record_likeness_review(
        manifest,
        decisions={"face-front": "pass", "full-body-front": "pass"},
        reviewed_by="operator",
        review_notes="Both required held-out comparisons are visually acceptable.",
        confirm_review_complete=True,
    )

    assert receipt["p1_static_teacher_status"] == "pass"
    assert receipt["p1_static_teacher_acceptance_authority"] is True
    assert receipt["human_visual_likeness_acceptance"] is True
    assert receipt["p2_animation_authorized"] is True
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_one_fail_records_completed_p1_failure_without_downstream_authority(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    output = tmp_path / "p1-review"
    manifest = build_likeness_review_pack(
        pairing,
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=output,
    )

    receipt = record_likeness_review(
        manifest,
        decisions={"face-front": "fail", "full-body-front": "pass"},
        reviewed_by="operator",
        review_notes="Face identity drifts in the held-out front comparison.",
        confirm_review_complete=True,
    )

    assert receipt["p1_static_teacher_status"] == "fail"
    assert receipt["human_visual_review_complete"] is True
    assert receipt["p1_static_teacher_acceptance_authority"] is False
    assert receipt["human_visual_likeness_acceptance"] is False
    assert receipt["p2_animation_authorized"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_review_requires_decision_for_every_criterion(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    manifest = build_likeness_review_pack(
        _pairing(teacher, reference),
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=tmp_path / "p1-review",
    )

    with pytest.raises(PhotorealP1LikenessReviewError, match="every criterion"):
        record_likeness_review(
            manifest,
            decisions={"face-front": "pass"},
            reviewed_by="operator",
            review_notes="Incomplete review should fail.",
            confirm_review_complete=True,
        )


def test_review_pack_rejects_changed_teacher_render(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    (teacher / "review" / "neutral-pose" / "25.png").write_bytes(b"tampered")

    with pytest.raises(PhotorealP1LikenessReviewError, match="teacher render .* bytes changed"):
        build_likeness_review_pack(
            pairing,
            teacher_output_root=teacher,
            appearance_review_root=reference,
            output_root=tmp_path / "p1-review",
        )


def test_review_pack_rejects_changed_held_out_reference(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    (reference / "frames" / "eval.png").write_bytes(b"tampered")

    with pytest.raises(PhotorealP1LikenessReviewError, match="held-out reference .* bytes changed"):
        build_likeness_review_pack(
            pairing,
            teacher_output_root=teacher,
            appearance_review_root=reference,
            output_root=tmp_path / "p1-review",
        )


def test_reuse_revalidates_html_and_copied_images(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    output = tmp_path / "p1-review"
    build_likeness_review_pack(
        pairing,
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=output,
    )
    (output / "review-index.html").write_text("<html>tampered</html>\n", encoding="utf-8")

    with pytest.raises(PhotorealP1LikenessReviewError, match="HTML bytes changed"):
        validate_likeness_review_pack(output, expected_pairing=pairing)


def test_final_receipt_validator_accepts_all_pass_against_exact_review_manifest(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    output = tmp_path / "p1-review"
    manifest = build_likeness_review_pack(
        pairing,
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=output,
    )
    receipt = record_likeness_review(
        manifest,
        decisions={"face-front": "pass", "full-body-front": "pass"},
        reviewed_by="operator",
        review_notes="Final human P1 review complete.",
        confirm_review_complete=True,
    )

    validated = validate_likeness_review_receipt(receipt, review_manifest=manifest)

    assert validated["p1_static_teacher_status"] == "pass"
    assert validated["p2_animation_authorized"] is True
    assert validated["photoreal_acceptance_authority"] is False
    assert validated["production_activation"] is False


def test_final_receipt_validator_rejects_resealed_status_that_disagrees_with_decisions(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    output = tmp_path / "p1-review"
    manifest = build_likeness_review_pack(
        pairing,
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=output,
    )
    receipt = record_likeness_review(
        manifest,
        decisions={"face-front": "fail", "full-body-front": "pass"},
        reviewed_by="operator",
        review_notes="One criterion failed.",
        confirm_review_complete=True,
    )
    receipt["p1_static_teacher_status"] = "pass"
    receipt["p1_static_teacher_acceptance_authority"] = True
    receipt["human_visual_likeness_acceptance"] = True
    receipt["p2_animation_authorized"] = True
    receipt["p1_likeness_review_sha256"] = _digest(
        receipt,
        omit="p1_likeness_review_sha256",
    )

    with pytest.raises(PhotorealP1LikenessReviewError, match="status does not match criterion decisions"):
        validate_likeness_review_receipt(receipt, review_manifest=manifest)


def test_final_receipt_validator_rejects_different_review_manifest(tmp_path: Path) -> None:
    teacher, reference = _roots(tmp_path)
    pairing = _pairing(teacher, reference)
    output = tmp_path / "p1-review"
    manifest = build_likeness_review_pack(
        pairing,
        teacher_output_root=teacher,
        appearance_review_root=reference,
        output_root=output,
    )
    receipt = record_likeness_review(
        manifest,
        decisions={"face-front": "pass", "full-body-front": "pass"},
        reviewed_by="operator",
        review_notes="Final human P1 review complete.",
        confirm_review_complete=True,
    )
    other_manifest = dict(manifest)
    other_manifest["selected_epoch_id"] = "epoch-b"
    other_manifest["p1_likeness_review_manifest_sha256"] = _digest(
        other_manifest,
        omit="p1_likeness_review_manifest_sha256",
    )

    with pytest.raises(PhotorealP1LikenessReviewError, match="targets different review manifest|provenance mismatch"):
        validate_likeness_review_receipt(receipt, review_manifest=other_manifest)
