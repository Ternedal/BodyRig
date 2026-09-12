from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_source_alignment import file_sha256
from bodyrig.recovery_throughput_human_review import (
    RecoveryThroughputHumanReviewError,
    record_review,
    verify_review,
)
from bodyrig.recovery_throughput_review_bundle import (
    FORMAT as BUNDLE_FORMAT,
    SEMANTICS as BUNDLE_SEMANTICS,
    VERSION as BUNDLE_VERSION,
    RecoveryThroughputReviewBundleError,
    verify_bundle,
)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _set_version(path: Path, version: object) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    value["version"] = version
    _write_json(path, value)
    return value


def _criteria() -> dict[str, str]:
    return {
        "identity_shape": "pass",
        "face_identity": "pass",
        "skin_texture_alignment": "pass",
        "gross_anatomy": "pass",
    }


def _fixture_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    (root / "baseline").mkdir(parents=True)
    (root / "candidate").mkdir(parents=True)
    (root / "baseline" / "front-full.png").write_bytes(b"baseline-image")
    (root / "candidate" / "front-full.png").write_bytes(b"candidate-image")
    (root / "index.html").write_text("<html>review</html>\n", encoding="utf-8")
    _write_json(
        root / "machine-audit.json",
        {
            "machine_evidence_pass": True,
            "decision": "eligible-for-human-ab-review",
            "promotion_authority": False,
            "production_activation": False,
        },
    )
    files = []
    for relative in (
        "baseline/front-full.png",
        "candidate/front-full.png",
        "index.html",
        "machine-audit.json",
    ):
        files.append({"path": relative, "sha256": file_sha256(root / relative)})
    _write_json(
        root / "review-bundle.json",
        {
            "format": BUNDLE_FORMAT,
            "version": BUNDLE_VERSION,
            "semantics": BUNDLE_SEMANTICS,
            "person_id": "person-" + "1" * 32,
            "baseline_job_id": "job-" + "2" * 32,
            "candidate_job_id": "job-" + "3" * 32,
            "baseline_bodyrig_revision": "8" * 40,
            "candidate_bodyrig_revision": "9" * 40,
            "baseline_package_sha256": "a" * 64,
            "candidate_package_sha256": "b" * 64,
            "views": [
                {
                    "view": "front-full",
                    "baseline_sha256": file_sha256(root / "baseline/front-full.png"),
                    "candidate_sha256": file_sha256(root / "candidate/front-full.png"),
                    "width": 1024,
                    "height": 1024,
                }
            ],
            "files": sorted(files, key=lambda item: item["path"]),
            "human_visual_review_required": True,
            "promotion_authority": False,
            "production_activation": False,
        },
    )
    return root


def test_review_bundle_rejects_boolean_v1_version(tmp_path: Path) -> None:
    root = _fixture_bundle(tmp_path)
    _set_version(root / "review-bundle.json", True)
    with pytest.raises(RecoveryThroughputReviewBundleError, match="format/version mismatch"):
        verify_bundle(root)


def test_human_review_rejects_boolean_v1_version(tmp_path: Path) -> None:
    root = _fixture_bundle(tmp_path)
    out = tmp_path / "human-review.json"
    record_review(
        root,
        out_path=out,
        reviewer="Fixture Reviewer",
        criteria=_criteria(),
        note="No material regression in reviewed views.",
    )
    _set_version(out, True)
    with pytest.raises(RecoveryThroughputHumanReviewError, match="format/version/semantics mismatch"):
        verify_review(out, bundle_dir=root)


def test_numeric_float_v1_survives_full_throughput_human_review_chain(tmp_path: Path) -> None:
    root = _fixture_bundle(tmp_path)
    bundle = _set_version(root / "review-bundle.json", 1.0)
    assert verify_bundle(root) == bundle

    out = tmp_path / "human-review.json"
    record_review(
        root,
        out_path=out,
        reviewer="Fixture Reviewer",
        criteria=_criteria(),
        note="No material regression in reviewed views.",
    )
    expected = _set_version(out, 1.0)
    verified = verify_review(out, bundle_dir=root)

    assert verified == expected
    assert verified["human_visual_review_passed"] is True
    assert verified["decision"] == "no-material-regression"
    assert verified["next_gate"] == "eligible-for-explicit-promotion-review"
    assert verified["review_bundle_receipt_sha256"] == file_sha256(root / "review-bundle.json")
    assert verified["machine_audit_sha256"] == file_sha256(root / "machine-audit.json")
    assert verified["promotion_authority"] is False
    assert verified["production_activation"] is False


def test_review_bundle_is_hash_bound_and_tamper_evident(tmp_path: Path) -> None:
    root = _fixture_bundle(tmp_path)
    receipt = verify_bundle(root)
    assert receipt["human_visual_review_required"] is True
    assert receipt["promotion_authority"] is False
    assert receipt["production_activation"] is False

    (root / "candidate/front-full.png").write_bytes(b"tampered")
    with pytest.raises(RecoveryThroughputReviewBundleError, match="has changed"):
        verify_bundle(root)


def test_human_review_is_create_only_external_and_never_promotion_authority(tmp_path: Path) -> None:
    root = _fixture_bundle(tmp_path)
    out = tmp_path / "human-review.json"
    criteria = _criteria()
    receipt = record_review(
        root,
        out_path=out,
        reviewer="Fixture Reviewer",
        criteria=criteria,
        note="No material regression in reviewed views.",
    )
    verified = verify_review(out, bundle_dir=root)
    assert receipt == verified
    assert verified["human_visual_review_passed"] is True
    assert verified["decision"] == "no-material-regression"
    assert verified["next_gate"] == "eligible-for-explicit-promotion-review"
    assert verified["promotion_authority"] is False
    assert verified["production_activation"] is False

    with pytest.raises(RecoveryThroughputHumanReviewError, match="refusing to overwrite"):
        record_review(
            root,
            out_path=out,
            reviewer="Fixture Reviewer",
            criteria=criteria,
            note="Second write must fail.",
        )


def test_failed_human_criterion_blocks_promotion_review(tmp_path: Path) -> None:
    root = _fixture_bundle(tmp_path)
    out = tmp_path / "failed-review.json"
    receipt = record_review(
        root,
        out_path=out,
        reviewer="Fixture Reviewer",
        criteria={
            "identity_shape": "pass",
            "face_identity": "fail",
            "skin_texture_alignment": "pass",
            "gross_anatomy": "pass",
        },
        note="Face identity regressed.",
    )
    assert receipt["human_visual_review_passed"] is False
    assert receipt["decision"] == "material-regression"
    assert receipt["next_gate"] == "blocked-material-regression"
    assert receipt["promotion_authority"] is False


def test_human_receipt_cannot_be_written_inside_immutable_bundle(tmp_path: Path) -> None:
    root = _fixture_bundle(tmp_path)
    with pytest.raises(RecoveryThroughputHumanReviewError, match="outside the immutable review bundle"):
        record_review(
            root,
            out_path=root / "human-review.json",
            reviewer="Fixture Reviewer",
            criteria=_criteria(),
            note="Invalid output location.",
        )
