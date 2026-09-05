from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from bodyrig.source_iris_isolation import SourceIrisIsolationError, build_candidate, read_candidate
from bodyrig.source_iris_isolation_review import (
    CHECKLIST_FIELDS,
    SourceIrisIsolationReviewError,
    read_review,
    write_review,
)

REVISION = "1" * 40


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _eye_png(path: Path) -> None:
    image = Image.new("RGBA", (64, 48), (235, 235, 230, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 10, 59, 39), fill=(225, 225, 218, 255))
    draw.ellipse((22, 12, 42, 36), fill=(105, 75, 45, 255))
    draw.ellipse((28, 18, 36, 30), fill=(25, 20, 18, 255))
    image.save(path, format="PNG")


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "eye-appearance"
    root.mkdir()
    left = root / "left_eye_appearance.png"
    right = root / "right_eye_appearance.png"
    bake = root / "canonical_eye_source_bake.png"
    _eye_png(left)
    _eye_png(right)
    Image.new("RGB", (64, 64), (128, 96, 72)).save(bake, format="PNG")
    receipt = {
        "format": "bodyrig-eye-appearance-candidate",
        "version": 1,
        "targetModelFamily": "female",
        "canonicalBakeSha256": _sha(bake),
        "leftEyeAppearancePngSha256": _sha(left),
        "rightEyeAppearancePngSha256": _sha(right),
        "sourceDerivedEyeSurfaceAppearance": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    (root / "eye-appearance-candidate.json").write_text(json.dumps(receipt), encoding="utf-8")
    return root


def _annotations() -> tuple[dict[str, int], dict[str, int]]:
    return ({"cx": 32, "cy": 24, "radius": 11}, {"cx": 32, "cy": 24, "radius": 11})


def _build(source: Path, out: Path) -> dict:
    left, right = _annotations()
    return build_candidate(
        source_eye_appearance_dir=source,
        output_dir=out,
        bodyrig_revision=REVISION,
        left_annotation=left,
        right_annotation=right,
    )


def test_candidate_is_source_and_revision_bound_and_cannot_grant_iris_authority(tmp_path: Path) -> None:
    source = _source(tmp_path)
    out = tmp_path / "iris"
    value = _build(source, out)
    verified = read_candidate(out, source_eye_appearance_dir=source)
    assert value["format"] == "bodyrig-source-iris-isolation-candidate"
    assert verified["bodyrigRevision"] == REVISION
    assert verified["sourceDerived"] is True
    assert verified["humanGuidedIsolation"] is True
    assert verified["irisIdentityIsolated"] is False
    assert verified["irisIsolationStatus"] == "candidate-human-review-required"
    assert verified["humanReviewRequired"] is True
    assert verified["eyeComponentAuthority"] is False
    assert verified["productionActivation"] is False
    assert verified["left"]["sourceOpaqueFraction"] >= 0.70
    assert verified["right"]["sourceOpaqueFraction"] >= 0.70
    assert Path(verified["leftPath"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_candidate_rejects_circle_outside_exact_source_crop(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(SourceIrisIsolationError, match="fully inside"):
        build_candidate(
            source_eye_appearance_dir=source,
            output_dir=tmp_path / "iris",
            bodyrig_revision=REVISION,
            left_annotation={"cx": 4, "cy": 4, "radius": 11},
            right_annotation={"cx": 32, "cy": 24, "radius": 11},
        )


def test_candidate_rejects_source_eye_bytes_changed_after_extraction(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (source / "left_eye_appearance.png").write_bytes((source / "left_eye_appearance.png").read_bytes() + b"x")
    left, right = _annotations()
    with pytest.raises(SourceIrisIsolationError, match="bytes changed"):
        build_candidate(
            source_eye_appearance_dir=source,
            output_dir=tmp_path / "iris",
            bodyrig_revision=REVISION,
            left_annotation=left,
            right_annotation=right,
        )


def test_candidate_rejects_annotation_receipt_tamper_even_when_png_bytes_are_unchanged(tmp_path: Path) -> None:
    source = _source(tmp_path)
    out = tmp_path / "iris"
    _build(source, out)
    receipt_path = out / "iris-isolation-candidate.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["left"]["annotation"]["cx"] += 1
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(SourceIrisIsolationError, match="deterministic source isolation"):
        read_candidate(out, source_eye_appearance_dir=source)


def test_human_review_is_the_only_step_that_grants_iris_isolation_authority(tmp_path: Path) -> None:
    source = _source(tmp_path)
    out = tmp_path / "iris"
    _build(source, out)
    result = write_review(
        candidate_dir=out,
        source_eye_appearance_dir=source,
        bodyrig_revision=REVISION,
        checklist={field: True for field in CHECKLIST_FIELDS},
        quality_note="Both iris boundaries match the exact source-derived eye crops; pupil and sclera are excluded.",
    )
    verified = read_review(candidate_dir=out, source_eye_appearance_dir=source)
    assert result["irisIdentityIsolated"] is True
    assert verified["bodyrigRevision"] == REVISION
    assert verified["irisAppearanceStatus"] == "source-isolated-review-pass"
    assert verified["humanReviewComplete"] is True
    assert verified["eyeComponentAuthority"] is False
    assert verified["eyesPromotionEligible"] is False
    assert verified["productionActivation"] is False


def test_review_rejects_different_checkout_revision_than_candidate(tmp_path: Path) -> None:
    source = _source(tmp_path)
    out = tmp_path / "iris"
    _build(source, out)
    with pytest.raises(SourceIrisIsolationReviewError, match="checkout revision mismatch"):
        write_review(
            candidate_dir=out,
            source_eye_appearance_dir=source,
            bodyrig_revision="2" * 40,
            checklist={field: True for field in CHECKLIST_FIELDS},
            quality_note="Wrong checkout fixture.",
        )


def test_review_requires_every_explicit_visual_check(tmp_path: Path) -> None:
    source = _source(tmp_path)
    out = tmp_path / "iris"
    _build(source, out)
    checklist = {field: True for field in CHECKLIST_FIELDS}
    checklist["sclera_not_included_as_iris_identity"] = False
    with pytest.raises(SourceIrisIsolationReviewError, match="sclera_not_included"):
        write_review(
            candidate_dir=out,
            source_eye_appearance_dir=source,
            bodyrig_revision=REVISION,
            checklist=checklist,
            quality_note="Rejected fixture.",
        )


def test_review_fails_closed_if_candidate_bytes_change_after_review(tmp_path: Path) -> None:
    source = _source(tmp_path)
    out = tmp_path / "iris"
    _build(source, out)
    write_review(
        candidate_dir=out,
        source_eye_appearance_dir=source,
        bodyrig_revision=REVISION,
        checklist={field: True for field in CHECKLIST_FIELDS},
        quality_note="Fixture PASS before tamper.",
    )
    (out / "left_iris_candidate.png").write_bytes((out / "left_iris_candidate.png").read_bytes() + b"tamper")
    with pytest.raises(SourceIrisIsolationReviewError, match="candidate authority failed"):
        read_review(candidate_dir=out, source_eye_appearance_dir=source)
