from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.high_fidelity_hfn_review as subject
from bodyrig.hands_feet_nails_authority import CHECKLIST_FIELDS


REVISION = "a" * 40
PERSON = "person-" + "1" * 32
BODY = "body-r0001"
CAPTURE = "hfncap-" + "2" * 32
CANDIDATE = "hfncand-" + "3" * 32


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _receipt() -> dict[str, object]:
    return {
        "format": subject.FORMAT,
        "version": subject.VERSION,
        "policy_revision": subject.POLICY_REVISION,
        "review_id": "hfnhuman-" + "4" * 32,
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": CAPTURE,
        "body_id": "body-" + "5" * 32,
        "candidate_id": CANDIDATE,
        "bodyrig_revision": REVISION,
        "candidate_receipt_sha256": _sha("candidate-receipt"),
        "candidate_package_sha256": _sha("candidate-package"),
        "source_capture_sha256": _sha("source-capture"),
        "render_manifest_sha256": _sha("render-manifest"),
        "render_region_sha256": {
            "left_hand": _sha("left-hand"),
            "right_hand": _sha("right-hand"),
            "left_foot": _sha("left-foot"),
            "right_foot": _sha("right-foot"),
        },
        "checklist": {name: True for name in sorted(CHECKLIST_FIELDS)},
        "quality_note": "Hænder, fødder, fingre, tæer og negle matcher kilden uden synlige artefakter.",
        "state": "pass",
        "source_grounded": True,
        "operator_supplied": True,
        "package_application_authority": False,
        "human_review_completed": True,
        "production_activation": False,
    }


def test_review_structure_requires_exact_m2_checklist_and_review_only_boundary() -> None:
    value = subject.validate_review_structure(_receipt())
    assert set(value["checklist"]) == CHECKLIST_FIELDS
    assert all(value["checklist"].values())
    assert value["source_grounded"] is True
    assert value["package_application_authority"] is False
    assert value["human_review_completed"] is True
    assert value["production_activation"] is False


@pytest.mark.parametrize("field,value", [
    ("source_grounded", False),
    ("operator_supplied", False),
    ("package_application_authority", True),
    ("human_review_completed", False),
    ("production_activation", True),
])
def test_review_structure_rejects_boundary_drift(field: str, value: object) -> None:
    receipt = _receipt()
    receipt[field] = value
    with pytest.raises(subject.HighFidelityHfnReviewError, match="review-only authority boundary"):
        subject.validate_review_structure(receipt)


def test_review_structure_rejects_partial_checklist_and_placeholder_note() -> None:
    receipt = _receipt()
    checklist = dict(receipt["checklist"])
    checklist[sorted(CHECKLIST_FIELDS)[0]] = False
    receipt["checklist"] = checklist
    with pytest.raises(subject.HighFidelityHfnReviewError, match="every canonical M2 checklist item"):
        subject.validate_review_structure(receipt)

    receipt = _receipt()
    receipt["quality_note"] = "<QUALITY_NOTE>"
    with pytest.raises(subject.HighFidelityHfnReviewError, match="real bounded quality note"):
        subject.validate_review_structure(receipt)


def test_review_id_binds_candidate_source_render_and_revision() -> None:
    first = subject._review_id(
        candidate_package_sha256=_sha("candidate"),
        source_capture_sha256=_sha("source"),
        render_manifest_sha256=_sha("render"),
        bodyrig_revision=REVISION,
    )
    changed = subject._review_id(
        candidate_package_sha256=_sha("candidate-2"),
        source_capture_sha256=_sha("source"),
        render_manifest_sha256=_sha("render"),
        bodyrig_revision=REVISION,
    )
    assert first.startswith("hfnhuman-")
    assert first != changed
