from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import high_fidelity_component_review as review


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
JOB_ID = "hfpreview-" + "1" * 32


def _preview() -> dict[str, Any]:
    return {
        "job_id": JOB_ID,
        "person_id": "person-" + "2" * 32,
        "body_revision": "body-r0001",
        "canonical_body_id": "body-test",
        "bodyrig_revision": "a" * 40,
        "target_family": "female",
        "candidate_package_sha256": "b" * 64,
        "anatomy_gate_sha256": "c" * 64,
        "component_discovery_sha256": "d" * 64,
        "review_vrm_sha256": "e" * 64,
        "comparison_authority_sha256": "f" * 64,
        "views": [
            {"view": name, "sha256": f"{index + 1:064x}"}
            for index, name in enumerate(review.VIEW_NAMES)
        ],
    }


def _receipt(preview: dict[str, Any], version: Any) -> dict[str, Any]:
    return {
        "format": review.FORMAT,
        "version": version,
        "policy_revision": review.POLICY_REVISION,
        "preview_job_id": preview["job_id"],
        "person_id": preview["person_id"],
        "body_revision": preview["body_revision"],
        "canonical_body_id": preview["canonical_body_id"],
        "bodyrig_revision": preview["bodyrig_revision"],
        "target_family": preview["target_family"],
        "candidate_package_sha256": preview["candidate_package_sha256"],
        "anatomy_gate_sha256": preview["anatomy_gate_sha256"],
        "component_discovery_sha256": preview["component_discovery_sha256"],
        "review_vrm_sha256": preview["review_vrm_sha256"],
        "comparison_authority_sha256": preview["comparison_authority_sha256"],
        "view_sha256": {
            item["view"]: item["sha256"]
            for item in preview["views"]
        },
        "reviewed_utc": "2026-09-14T18:00:00Z",
        "checklist": {field: True for field in review.CHECKLIST_FIELDS},
        "quality_note": "Human visual component review passed for this exact preview evidence.",
        "review_outcome": dict(review.REVIEW_OUTCOME),
        "promotion_eligibility": dict(review.PROMOTION_ELIGIBILITY),
        "human_review_complete": True,
        "production_activation": False,
    }


def _write_and_bind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: Any) -> None:
    preview = _preview()
    path = tmp_path / "component-review.json"
    path.write_text(
        json.dumps(_receipt(preview, version), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setattr(review, "_preview_authority", lambda _job_id: preview)
    monkeypatch.setattr(review, "review_path", lambda *_args, **_kwargs: path)


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_component_review_readback_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    _write_and_bind(monkeypatch, tmp_path, version)

    with pytest.raises(
        review.HighFidelityComponentReviewError,
        match="component visual review format/version/policy mismatch",
    ):
        review.read_review(JOB_ID)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_component_review_readback_preserves_numeric_v1_and_promotion_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    _write_and_bind(monkeypatch, tmp_path, version)

    value = review.read_review(JOB_ID)

    assert value["version"] == version
    assert value["review_outcome"] == review.REVIEW_OUTCOME
    assert value["promotion_eligibility"] == review.PROMOTION_ELIGIBILITY
    assert value["human_review_complete"] is True
    assert value["production_activation"] is False
