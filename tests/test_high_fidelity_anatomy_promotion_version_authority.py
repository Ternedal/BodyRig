from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bodyrig import high_fidelity_anatomy_promotion as promotion


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
JOB_ID = "hfpreview-" + "1" * 32
BODY_ID = "body-test"


def _review() -> dict[str, Any]:
    return {
        "preview_job_id": JOB_ID,
        "canonical_body_id": BODY_ID,
        "bodyrig_revision": "a" * 40,
        "target_family": "female",
        "anatomy_gate_sha256": "b" * 64,
        "review_vrm_sha256": "c" * 64,
    }


def _embedded(review: dict[str, Any], source_sha: str, review_sha: str) -> dict[str, Any]:
    return {
        "format": promotion.EMBEDDED_FORMAT,
        "version": promotion.VERSION,
        "policyRevision": promotion.POLICY_REVISION,
        "previewJobId": review["preview_job_id"],
        "componentReviewSha256": review_sha,
        "sourcePackageSha256": source_sha,
        "anatomyGateSha256": review["anatomy_gate_sha256"],
        "bodyrigRevision": review["bodyrig_revision"],
        "targetFamily": review["target_family"],
        "component": "body_anatomy",
        "productionActivation": False,
    }


def _bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: Any) -> None:
    review = _review()
    source = tmp_path / "source.mrbody"
    source.write_bytes(b"source-package")
    review_receipt = tmp_path / "component-review.json"
    review_receipt.write_bytes(b"component-review")
    destination = tmp_path / "promoted.mrbody"
    avatar = b"promoted-avatar"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("avatar.vrm", avatar)
    receipt_path = tmp_path / "promotion.json"

    source_sha = promotion._sha256_file(source)
    review_sha = promotion._sha256_file(review_receipt)
    before = {"body_anatomy": "pending", "hair": "pending", "eyes": "pending"}
    after = {"body_anatomy": "complete", "hair": "pending", "eyes": "pending"}
    receipt = {
        "format": promotion.FORMAT,
        "version": version,
        "policy_revision": promotion.POLICY_REVISION,
        "preview_job_id": review["preview_job_id"],
        "canonical_body_id": review["canonical_body_id"],
        "bodyrig_revision": review["bodyrig_revision"],
        "target_family": review["target_family"],
        "source_package_sha256": source_sha,
        "component_review_sha256": review_sha,
        "anatomy_gate_sha256": review["anatomy_gate_sha256"],
        "promoted_package_sha256": promotion._sha256_file(destination),
        "promoted_avatar_sha256": promotion._sha256_bytes(avatar),
        "components_before": before,
        "components_after": after,
        "promotion_component": "body_anatomy",
        "production_activation": False,
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    monkeypatch.setattr(promotion, "read_review", lambda _job_id: review)
    monkeypatch.setattr(promotion, "_candidate_package", lambda _review: source)
    monkeypatch.setattr(promotion, "_promotion_paths", lambda _review: (destination, receipt_path))
    monkeypatch.setattr(promotion, "_review_receipt_path", lambda _review: review_receipt)
    monkeypatch.setattr(
        promotion,
        "validate_package",
        lambda _path: SimpleNamespace(manifest={"id": BODY_ID}),
    )
    monkeypatch.setattr(
        promotion,
        "audit_high_fidelity_package",
        lambda path: {
            "components": after if Path(path) == destination else before,
            "production_ready": False,
        },
    )
    monkeypatch.setattr(
        promotion,
        "_embedded_promotion",
        lambda _path: _embedded(review, source_sha, review_sha),
    )


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_anatomy_promotion_readback_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    _bind(monkeypatch, tmp_path, version)

    with pytest.raises(
        promotion.HighFidelityAnatomyPromotionError,
        match="anatomy promotion format/version/policy mismatch",
    ):
        promotion.read_promotion(JOB_ID)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_anatomy_promotion_readback_preserves_numeric_v1_and_anatomy_only_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    _bind(monkeypatch, tmp_path, version)

    value = promotion.read_promotion(JOB_ID)

    assert value["version"] == version
    assert value["promotion_component"] == "body_anatomy"
    assert value["components_before"]["body_anatomy"] == "pending"
    assert value["components_after"]["body_anatomy"] == "complete"
    assert value["components_after"]["hair"] == "pending"
    assert value["components_after"]["eyes"] == "pending"
    assert value["production_activation"] is False
