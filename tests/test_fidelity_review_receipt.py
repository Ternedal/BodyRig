from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.fidelity_review_receipt import (
    BOUND_FILES,
    RECEIPT_NAME,
    FidelityReviewReceiptError,
    seal_review_bundle,
    verify_review_bundle,
)

HISTORICAL = "0" * 64
PR40 = "1" * 64
PR41 = "2" * 64


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    evidence = {
        "format": "bodyrig-fidelity-ab-evidence",
        "version": 1,
        "left": {"package_sha256": PR40},
        "right": {"package_sha256": PR41},
        "invariants": {"clean_appearance_ab": True},
        "human_visual_authority_required": True,
        "comparison_only": True,
        "production_activation": False,
    }
    evidence_path = root / "fidelity-ab-evidence.json"
    for name in BOUND_FILES:
        path = root / name
        if name == "fidelity-ab-evidence.json":
            path.write_text(json.dumps(evidence), encoding="utf-8")
        elif name == "index.html":
            path.write_text("<html>review</html>", encoding="utf-8")
        elif name.endswith(".json"):
            path.write_text(json.dumps({"fixture": name}), encoding="utf-8")
        else:
            path.write_bytes(("fixture:" + name).encode("utf-8"))
    return root, evidence_path


def _verify(root: Path, evidence_path: Path):
    return verify_review_bundle(
        root,
        expected_historical_package_sha256=HISTORICAL,
        expected_pr40_package_sha256=PR40,
        expected_pr41_package_sha256=PR41,
        expected_evidence_sha256=_sha(evidence_path),
    )


def test_review_receipt_seals_and_verifies_exact_bundle_bytes(tmp_path: Path) -> None:
    root, evidence_path = _bundle(tmp_path / "review")
    receipt_path = seal_review_bundle(
        root,
        historical_package_sha256=HISTORICAL,
        pr40_package_sha256=PR40,
        pr41_package_sha256=PR41,
        evidence_sha256=_sha(evidence_path),
    )
    assert receipt_path == root / RECEIPT_NAME
    receipt = _verify(root, evidence_path)
    assert receipt["packages"] == {"historical": HISTORICAL, "pr40": PR40, "pr41": PR41}
    assert receipt["human_visual_authority_required"] is True
    assert receipt["production_activation"] is False


def test_review_receipt_is_create_only_and_rejects_pixel_or_html_tamper(tmp_path: Path) -> None:
    root, evidence_path = _bundle(tmp_path / "review")
    seal_review_bundle(
        root,
        historical_package_sha256=HISTORICAL,
        pr40_package_sha256=PR40,
        pr41_package_sha256=PR41,
        evidence_sha256=_sha(evidence_path),
    )
    with pytest.raises(FidelityReviewReceiptError, match="already exists"):
        seal_review_bundle(
            root,
            historical_package_sha256=HISTORICAL,
            pr40_package_sha256=PR40,
            pr41_package_sha256=PR41,
            evidence_sha256=_sha(evidence_path),
        )

    image = root / "pr41-face-front.png"
    image.write_bytes(image.read_bytes() + b"tamper")
    with pytest.raises(FidelityReviewReceiptError, match="file hash mismatch"):
        _verify(root, evidence_path)


def test_review_receipt_rejects_evidence_or_file_set_substitution(tmp_path: Path) -> None:
    root, evidence_path = _bundle(tmp_path / "review")
    seal_review_bundle(
        root,
        historical_package_sha256=HISTORICAL,
        pr40_package_sha256=PR40,
        pr41_package_sha256=PR41,
        evidence_sha256=_sha(evidence_path),
    )

    with pytest.raises(FidelityReviewReceiptError, match="package authority mismatch"):
        verify_review_bundle(
            root,
            expected_historical_package_sha256=HISTORICAL,
            expected_pr40_package_sha256="3" * 64,
            expected_pr41_package_sha256=PR41,
            expected_evidence_sha256=_sha(evidence_path),
        )

    extra = root / "unbound.txt"
    extra.write_text("unexpected", encoding="utf-8")
    with pytest.raises(FidelityReviewReceiptError, match="missing or unexpected top-level files"):
        _verify(root, evidence_path)
