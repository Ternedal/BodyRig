from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.high_fidelity_human_review import (
    CHECKLIST_FIELDS,
    HighFidelityHumanReviewError,
    read_review,
    review_path,
    review_status,
    write_review,
)

BODY_ID = "bodyid-" + "a" * 24


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package(tmp_path: Path) -> Path:
    path = tmp_path / f"{BODY_ID}.mrbody"
    path.write_bytes(b"exact-body-package")
    return path


def _audit(package: Path, *, ready: bool = True, state_marker: str = "v1") -> dict:
    components = {
        "body_anatomy": "complete" if ready else "not-evaluated",
        "skin_appearance": "complete" if ready else "partial",
        "hair": "complete" if ready else "missing",
        "eyes": "complete" if ready else "partial",
        "face_secondary": "complete" if ready else "missing",
    }
    face = {
        "eyebrow_appearance": "complete" if ready else "not-evaluated",
        "lip_boundary": "complete" if ready else "not-evaluated",
        "mouth_interior": "complete" if ready else "missing",
        "teeth": "complete" if ready else "missing",
        "eyelashes": "complete" if ready else "missing",
    }
    if state_marker != "v1" and ready:
        # Same package bytes, different component authority: a prior review must not survive it.
        components["skin_appearance"] = f"complete-{state_marker}"
    return {
        "canonical_body_id": BODY_ID,
        "package_sha256": _sha(package),
        "components": components,
        "high_fidelity_ready": ready,
        "top_level_blockers": [] if ready else [name for name, value in components.items() if value != "complete"],
        "face_secondary_components": face,
        "face_secondary_ready": ready,
        "face_secondary_blockers": [] if ready else [name for name, value in face.items() if value != "complete"],
        "semantic_vertex_map_authority": "licensed-smplx-verified" if ready else "unavailable",
        "human_review_required": True,
    }


def _checklist() -> dict[str, bool]:
    return {field: True for field in CHECKLIST_FIELDS}


def test_review_status_is_blocked_until_component_gates_are_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: _audit(package, ready=False))

    status = review_status(package)

    assert status["state"] == "blocked"
    assert status["passed"] is False
    assert "component gates" in status["reason"]
    with pytest.raises(HighFidelityHumanReviewError, match="cannot be recorded before all component gates"):
        write_review(package, checklist=_checklist(), quality_note="reviewed")


def test_complete_components_require_explicit_review_before_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: _audit(package))

    status = review_status(package)

    assert status["state"] == "required"
    assert status["passed"] is False
    assert "Explicit high-fidelity human review is required" in status["reason"]


def test_write_and_read_review_are_exact_package_and_component_state_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    audit = _audit(package)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: audit)

    receipt = write_review(package, checklist=_checklist(), quality_note="Hair, eyes, face and body reviewed physically.")
    loaded = read_review(package)
    status = review_status(package)

    assert receipt == loaded
    assert receipt["body_id"] == BODY_ID
    assert receipt["package_sha256"] == _sha(package)
    assert len(receipt["component_state_sha256"]) == 64
    assert set(receipt["checklist"]) == CHECKLIST_FIELDS
    assert all(receipt["checklist"].values())
    assert receipt["human_review_complete"] is True
    assert receipt["production_activation"] is False
    assert status["state"] == "pass"
    assert status["passed"] is True
    assert status["quality_note"] == receipt["quality_note"]


def test_review_is_create_only_for_exact_package_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: _audit(package))
    write_review(package, checklist=_checklist(), quality_note="first review")

    with pytest.raises(HighFidelityHumanReviewError, match="refusing to overwrite"):
        write_review(package, checklist=_checklist(), quality_note="second review")


def test_review_requires_every_explicit_checklist_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: _audit(package))
    checklist = _checklist()
    checklist["hair_geometry_appearance_acceptable"] = False

    with pytest.raises(HighFidelityHumanReviewError, match="hair_geometry_appearance_acceptable"):
        write_review(package, checklist=checklist, quality_note="not actually complete")


def test_review_requires_non_empty_quality_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: _audit(package))

    with pytest.raises(HighFidelityHumanReviewError, match="non-empty quality note"):
        write_review(package, checklist=_checklist(), quality_note="   ")


def test_review_status_rejects_stale_audit_package_sha_before_sidecar_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    audit = _audit(package)
    audit["package_sha256"] = "9" * 64
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: audit)

    with pytest.raises(HighFidelityHumanReviewError, match="audit package SHA no longer matches package bytes"):
        review_status(package)


def test_review_does_not_survive_package_byte_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    first_audit = _audit(package)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: first_audit)
    write_review(package, checklist=_checklist(), quality_note="review for original bytes")
    original_review = review_path(package)
    assert original_review.is_file()

    package.write_bytes(b"changed-package-bytes")
    changed_audit = _audit(package)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: changed_audit)

    status = review_status(package)
    assert status["state"] == "required"
    assert status["passed"] is False
    assert review_path(package) != original_review
    assert original_review.is_file()


def test_component_state_drift_invalidates_existing_review_even_when_package_sha_is_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    current = {"value": _audit(package, state_marker="v1")}
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: current["value"])
    write_review(package, checklist=_checklist(), quality_note="reviewed v1 state")

    current["value"] = _audit(package, state_marker="v2")
    with pytest.raises(HighFidelityHumanReviewError, match="no longer matches current component-state authority"):
        read_review(package)
    with pytest.raises(HighFidelityHumanReviewError, match="no longer matches current component-state authority"):
        review_status(package)


def test_tampered_review_cannot_activate_or_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr("bodyrig.high_fidelity_human_review.audit_high_fidelity_package", lambda _: _audit(package))
    write_review(package, checklist=_checklist(), quality_note="reviewed")
    path = review_path(package)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["production_activation"] = True
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    with pytest.raises(HighFidelityHumanReviewError, match="must remain independently non-activating"):
        read_review(package)
    with pytest.raises(HighFidelityHumanReviewError, match="must remain independently non-activating"):
        review_status(package)
