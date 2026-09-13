from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_hfn_continuation as continuation
import bodyrig.high_fidelity_hfn_review as review
from bodyrig.hands_feet_nails_authority import CHECKLIST_FIELDS


SHA = "a" * 64
REVISION = "b" * 40
PERSON = "person-" + "1" * 32
BODY = "body-r0001"
CAPTURE = "hfncap-" + "2" * 32
CANDIDATE = "hfncand-" + "3" * 32
REVIEW = "hfnhuman-" + "4" * 32


def _review_receipt(version: object) -> dict[str, object]:
    return {
        "format": review.FORMAT,
        "version": version,
        "policy_revision": review.POLICY_REVISION,
        "review_id": REVIEW,
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": CAPTURE,
        "body_id": "body-example",
        "candidate_id": CANDIDATE,
        "bodyrig_revision": REVISION,
        "candidate_receipt_sha256": "1" * 64,
        "candidate_package_sha256": "2" * 64,
        "source_capture_sha256": "3" * 64,
        "render_manifest_sha256": "4" * 64,
        "render_region_sha256": {
            "left_hand": "5" * 64,
            "right_hand": "6" * 64,
            "left_foot": "7" * 64,
            "right_foot": "8" * 64,
        },
        "checklist": {name: True for name in CHECKLIST_FIELDS},
        "quality_note": "Physically inspected canonical HFN views.",
        "state": "pass",
        "source_grounded": True,
        "operator_supplied": True,
        "package_application_authority": False,
        "human_review_completed": True,
        "production_activation": False,
    }


def test_candidate_discovery_rejects_boolean_v1_and_preserves_numeric_v1() -> None:
    raw = {
        "format": "bodyrig-hands-feet-nails-detail-candidate",
        "version": True,
        "source_package_sha256": SHA,
        "bodyrig_revision": REVISION,
    }
    assert continuation._candidate_receipt_matches(
        raw,
        source_package_sha256=SHA,
        bodyrig_revision=REVISION,
    ) is False

    raw["version"] = 1.0
    assert continuation._candidate_receipt_matches(
        raw,
        source_package_sha256=SHA,
        bodyrig_revision=REVISION,
    ) is True


def test_hfn_human_review_rejects_boolean_v1_and_preserves_numeric_v1() -> None:
    with pytest.raises(review.HighFidelityHfnReviewError, match="format/version/policy/state"):
        review.validate_review_structure(_review_receipt(True))

    value = review.validate_review_structure(_review_receipt(1.0))
    assert value["version"] == 1.0
    assert value["production_activation"] is False


def test_strict_candidate_and_source_readers_reject_boolean_v1(monkeypatch) -> None:
    candidate = {
        "version": True,
        "bodyrig_revision": REVISION,
    }
    monkeypatch.setattr(review, "read_detail_candidate", lambda *args, **kwargs: candidate)
    with pytest.raises(review.HighFidelityHfnReviewError, match="candidate version"):
        review._read_candidate_strict(
            Path("."),
            person_id=PERSON,
            body_revision=BODY,
            capture_id=CAPTURE,
            candidate_id=CANDIDATE,
        )

    candidate["version"] = 1.0
    assert review._read_candidate_strict(
        Path("."),
        person_id=PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
        candidate_id=CANDIDATE,
    )["version"] == 1.0

    source = {"version": True}
    monkeypatch.setattr(review, "read_source_capture", lambda *args, **kwargs: source)
    with pytest.raises(review.HighFidelityHfnReviewError, match="source-capture version"):
        review._read_source_capture_strict(
            Path("."),
            person_id=PERSON,
            body_revision=BODY,
            capture_id=CAPTURE,
        )

    source["version"] = 1.0
    assert review._read_source_capture_strict(
        Path("."),
        person_id=PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
    )["version"] == 1.0


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _render_fixture(tmp_path: Path, *, manifest_version: object = 1, comparison_version: object = 1, authority_version: object = 1):
    render_dir = tmp_path / "render"
    manifest_path = render_dir / "snapshots" / "hands-feet-nails-render-set.json"
    comparison_path = render_dir / "comparison-authority.json"
    authority_path = render_dir / "hands-feet-nails-render-authority.json"
    manifest_sha = "9" * 64
    regions = {
        "left_hand": "1" * 64,
        "right_hand": "2" * 64,
        "left_foot": "3" * 64,
        "right_foot": "4" * 64,
    }
    comparison = {
        "format": "bodyrig-fidelity-comparison-authority",
        "version": comparison_version,
        "authority": "validated-package-comparison-only",
        "bodyrig_revision": REVISION,
        "runtime_manifest_sha256": "5" * 64,
        "package_sha256": "6" * 64,
        "physical_acceptance_authority": False,
        "comparison_only": True,
        "production_activation": False,
    }
    _write_json(comparison_path, comparison)
    comparison_sha = hashlib.sha256(comparison_path.read_bytes()).hexdigest()
    authority = {
        "format": "bodyrig-hands-feet-nails-render-authority",
        "version": authority_version,
        "bodyrig_revision": REVISION,
        "body_id": "body-example",
        "package_sha256": "6" * 64,
        "runtime_manifest_sha256": "5" * 64,
        "comparison_authority_sha256": comparison_sha,
        "render_manifest_sha256": manifest_sha,
        "render_region_sha256": regions,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }
    _write_json(authority_path, authority)
    _write_json(manifest_path, {"version": manifest_version})
    candidate = {
        "version": 1,
        "body_id": "body-example",
        "candidate_package_sha256": "6" * 64,
    }
    return render_dir, candidate, manifest_sha, regions


@pytest.mark.parametrize(
    ("manifest_version", "comparison_version", "authority_version", "match"),
    [
        (True, 1, 1, "render-manifest version"),
        (1, True, 1, "comparison-authority"),
        (1, 1, True, "render-authority"),
    ],
)
def test_render_chain_rejects_boolean_v1(
    monkeypatch,
    tmp_path: Path,
    manifest_version: object,
    comparison_version: object,
    authority_version: object,
    match: str,
) -> None:
    render_dir, candidate, manifest_sha, regions = _render_fixture(
        tmp_path,
        manifest_version=manifest_version,
        comparison_version=comparison_version,
        authority_version=authority_version,
    )
    monkeypatch.setattr(
        continuation,
        "validate_render_manifest",
        lambda *args, **kwargs: {
            "manifest": {"version": manifest_version},
            "manifest_sha256": manifest_sha,
            "region_sha256": regions,
        },
    )

    with pytest.raises(continuation.HighFidelityHfnContinuationError, match=match):
        continuation._validate_render_authority(
            render_dir,
            candidate=candidate,
            bodyrig_revision=REVISION,
        )


def test_render_chain_preserves_numeric_v1(monkeypatch, tmp_path: Path) -> None:
    render_dir, candidate, manifest_sha, regions = _render_fixture(
        tmp_path,
        manifest_version=1.0,
        comparison_version=1.0,
        authority_version=1.0,
    )
    monkeypatch.setattr(
        continuation,
        "validate_render_manifest",
        lambda *args, **kwargs: {
            "manifest": {"version": 1.0},
            "manifest_sha256": manifest_sha,
            "region_sha256": regions,
        },
    )

    result = continuation._validate_render_authority(
        render_dir,
        candidate=candidate,
        bodyrig_revision=REVISION,
    )
    assert result["manifest_sha256"] == manifest_sha
