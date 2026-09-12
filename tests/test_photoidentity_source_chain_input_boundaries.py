from __future__ import annotations

import pytest

from bodyrig.photoidentity_source_chain import (
    PhotoIdentitySourceChainError,
    _assert_claims_match,
    _quality,
    _receipt_boundary,
)


def _receipt(*, version: object = 1) -> dict[str, object]:
    return {
        "format": "test-source-attestation",
        "version": version,
        "operator_supplied": True,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
        "quality_note": "Reviewed the exact source evidence for this attestation.",
    }


def _observations(*, quality: object) -> dict[str, object]:
    return {
        "detail_evidence": {
            "fingernails_detail": [
                {
                    "scene_id": "scene-a",
                    "quality": quality,
                    "source_derived": True,
                    "adapter": "human-source-nail-detail-attestation",
                    "revision": "1",
                }
            ]
        }
    }


def test_quality_normalizes_arbitrary_precision_overflow() -> None:
    with pytest.raises(PhotoIdentitySourceChainError, match="source quality is outside 0..1"):
        _quality(10**400, label="source quality")


def test_quality_preserves_ordinary_valid_value() -> None:
    assert _quality(0.91, label="source quality") == 0.91


def test_receipt_boundary_rejects_boolean_version() -> None:
    with pytest.raises(PhotoIdentitySourceChainError, match="authority boundary is invalid"):
        _receipt_boundary(
            _receipt(version=True),
            expected_format="test-source-attestation",
            label="Source attestation",
        )


def test_receipt_boundary_preserves_numeric_v1_compatibility() -> None:
    _receipt_boundary(
        _receipt(version=1.0),
        expected_format="test-source-attestation",
        label="Source attestation",
    )


def test_final_claim_quality_normalizes_arbitrary_precision_overflow() -> None:
    with pytest.raises(
        PhotoIdentitySourceChainError,
        match="final fingernails_detail claim quality is outside 0..1",
    ):
        _assert_claims_match(
            _observations(quality=10**400),
            domain="fingernails_detail",
            expected=[{"scene_id": "scene-a", "quality": 0.91}],
            adapter="human-source-nail-detail-attestation",
        )


def test_final_claim_quality_preserves_exact_valid_match() -> None:
    _assert_claims_match(
        _observations(quality=0.91),
        domain="fingernails_detail",
        expected=[{"scene_id": "scene-a", "quality": 0.91}],
        adapter="human-source-nail-detail-attestation",
    )
