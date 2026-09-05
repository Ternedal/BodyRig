from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_human_review as review


BODY_ID = "bodyid-" + "d" * 24


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package(tmp_path: Path) -> Path:
    package = tmp_path / f"{BODY_ID}.mrbody"
    package.write_bytes(b"exact-promoted-package")
    return package


def _audit(package: Path) -> dict:
    return {
        "canonical_body_id": BODY_ID,
        "package_sha256": _sha(package),
        "components": {
            "body_anatomy": "complete",
            "skin_appearance": "complete",
            "hair": "complete",
            "eyes": "complete",
            "face_secondary": "complete",
        },
        "high_fidelity_ready": True,
        "top_level_blockers": [],
        "face_secondary_components": {
            "eyebrow_appearance": "complete",
            "lip_boundary": "complete",
            "mouth_interior": "complete",
            "teeth": "complete",
            "eyelashes": "complete",
        },
        "face_secondary_ready": True,
        "face_secondary_blockers": [],
        "semantic_vertex_map_authority": "licensed-smplx-verified",
        "human_review_required": True,
    }


def _checklist() -> dict[str, bool]:
    return {field: True for field in review.CHECKLIST_FIELDS}


def _tamper_to_placeholder(package: Path) -> tuple[Path, bytes]:
    path = review.review_path(package)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["quality_note"] = "<QUALITY_NOTE>"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, path.read_bytes()


def test_invalid_review_is_archived_content_addressed_and_status_returns_to_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr(review, "audit_high_fidelity_package", lambda _path: _audit(package))
    review.write_review(package, checklist=_checklist(), quality_note="Reviewed exact package physically.")
    canonical, invalid_bytes = _tamper_to_placeholder(package)

    recovery = review.invalid_review_recovery_status(package)

    assert recovery["available"] is True
    assert recovery["review_path"] == str(canonical)
    assert recovery["receipt_sha256"] == hashlib.sha256(invalid_bytes).hexdigest()
    assert "placeholder" in recovery["reason"]

    result = review.archive_invalid_review(package)
    archive = Path(result["archived_review_path"])

    assert result["ok"] is True
    assert result["production_activation"] is False
    assert result["package_sha256"] == _sha(package)
    assert result["receipt_sha256"] == hashlib.sha256(invalid_bytes).hexdigest()
    assert archive.is_file()
    assert archive.read_bytes() == invalid_bytes
    assert not canonical.exists()
    assert review.review_status(package)["state"] == "required"


def test_valid_review_cannot_be_archived_for_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr(review, "audit_high_fidelity_package", lambda _path: _audit(package))
    review.write_review(package, checklist=_checklist(), quality_note="Real operator review.")
    canonical = review.review_path(package)

    status = review.invalid_review_recovery_status(package)

    assert status["available"] is False
    assert "valid" in status["reason"].lower()
    with pytest.raises(review.HighFidelityHumanReviewError, match="refusing human-review recovery"):
        review.archive_invalid_review(package)
    assert canonical.is_file()


def test_conflicting_archive_never_deletes_invalid_canonical_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr(review, "audit_high_fidelity_package", lambda _path: _audit(package))
    review.write_review(package, checklist=_checklist(), quality_note="Real operator review.")
    canonical, invalid_bytes = _tamper_to_placeholder(package)
    receipt_sha = hashlib.sha256(invalid_bytes).hexdigest()
    archive = review.invalid_review_archive_path(package, receipt_sha256=receipt_sha)
    archive.write_bytes(b"conflicting-archive-bytes")

    with pytest.raises(review.HighFidelityHumanReviewError, match="different bytes"):
        review.archive_invalid_review(package)

    assert canonical.is_file()
    assert canonical.read_bytes() == invalid_bytes
    assert archive.read_bytes() == b"conflicting-archive-bytes"
