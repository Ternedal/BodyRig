from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_human_review as review


ROOT = Path(__file__).resolve().parents[1]
BODY_ID = "bodyid-" + "a" * 24


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package(tmp_path: Path) -> Path:
    package = tmp_path / f"{BODY_ID}.mrbody"
    package.write_bytes(b"exact-high-fidelity-package")
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


def test_human_review_operator_accepts_installed_body_or_exact_package_but_not_both() -> None:
    wrapper = (ROOT / "record-high-fidelity-human-review.ps1").read_text(encoding="utf-8")

    assert '[string]$BodyId = ""' in wrapper
    assert '[string]$PackagePath = ""' in wrapper
    assert "$hasBodyId -eq $hasPackage" in wrapper
    assert "Specify exactly one high-fidelity review source" in wrapper
    assert '@("--body-id", $BodyId)' in wrapper
    assert '@("--package", $PackagePath)' in wrapper


def test_package_review_is_hash_checked_before_and_after_receipt_creation() -> None:
    wrapper = (ROOT / "record-high-fidelity-human-review.ps1").read_text(encoding="utf-8")

    assert "Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256" in wrapper
    assert "reviewed different package bytes" in wrapper
    assert "Reviewed high-fidelity package bytes changed after receipt creation" in wrapper
    assert "Remove-Item -LiteralPath $reviewPath -Force" in wrapper
    assert "production_activation=false" in wrapper


def test_human_review_cli_still_supports_package_bound_review() -> None:
    cli = (ROOT / "bodyrig" / "high_fidelity_human_review_cli.py").read_text(encoding="utf-8")

    assert 'source.add_argument("--package"' in cli
    assert "write_review(" in cli
    assert "read_review(package)" in cli
    assert '"production_activation": False' in cli


def test_write_review_rejects_generated_quality_note_placeholder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr(review, "audit_high_fidelity_package", lambda _: _audit(package))

    with pytest.raises(review.HighFidelityHumanReviewError, match="generated placeholder"):
        review.write_review(package, checklist=_checklist(), quality_note="<QUALITY_NOTE>")

    assert not review.review_path(package).exists()


def test_read_review_rejects_placeholder_tamper_even_when_other_authority_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr(review, "audit_high_fidelity_package", lambda _: _audit(package))
    review.write_review(package, checklist=_checklist(), quality_note="Actual physical review performed.")
    path = review.review_path(package)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["quality_note"] = "<your physical high-fidelity review>"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    with pytest.raises(review.HighFidelityHumanReviewError, match="generated placeholder"):
        review.read_review(package)


def test_review_wrapper_matches_validated_python_runtime_and_rejects_placeholder_before_cli() -> None:
    wrapper = (ROOT / "record-high-fidelity-human-review.ps1").read_text(encoding="utf-8")
    status = (ROOT / "high-fidelity-physical-status.ps1").read_text(encoding="utf-8")

    for token in (
        '.venv\\Scripts\\python.exe',
        "Test-Path -LiteralPath $pythonCandidate -PathType Leaf",
        "Get-Command python -ErrorAction SilentlyContinue",
        '$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }',
        "bodyrig.__file__",
    ):
        assert token in wrapper
        assert token in status

    placeholder_guard = wrapper.index("$QualityNote -match '^<[^>]+>$'")
    python_cli = wrapper.index("-m bodyrig.high_fidelity_human_review_cli")
    pythonpath = wrapper.index("$env:PYTHONPATH = if")
    module_authority = wrapper.index("bodyrig.__file__")

    assert placeholder_guard < pythonpath < module_authority < python_cli
    assert "actual high-fidelity review" in wrapper
