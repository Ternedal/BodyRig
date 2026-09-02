from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_reconstruction_model_family_audit import (  # noqa: E402
    ReconstructionModelFamilyAuditError,
    build_receipt,
)


def test_model_family_receipt_records_unique_reconstruction_authority() -> None:
    receipt = build_receipt(
        {
            "female": (0.0002, 0.00005),
            "male": (0.031, 0.011),
            "neutral": (0.018, 0.007),
        }
    )

    assert receipt["authorityModelFamily"] == "female"
    assert receipt["fitMetrics"]["female"]["withinStrictBounds"] is True
    assert receipt["fitMetrics"]["male"]["withinStrictBounds"] is False
    assert receipt["retainedReconstructionIsAuthority"] is True
    assert receipt["operatorOverrideAllowed"] is False
    assert receipt["geometryModified"] is False
    assert receipt["reconstructionRerun"] is False
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False


def test_model_family_receipt_rejects_non_unique_claim() -> None:
    with pytest.raises(RuntimeError, match="ambiguous"):
        build_receipt(
            {
                "female": (0.0002, 0.00005),
                "neutral": (0.0003, 0.00008),
            }
        )


def test_model_family_receipt_rejects_authority_outside_strict_bounds() -> None:
    with pytest.raises(ReconstructionModelFamilyAuditError, match="does not satisfy strict"):
        build_receipt(
            {
                "female": (0.02, 0.01),
                "male": (0.03, 0.02),
                "neutral": (0.04, 0.03),
            },
            authority_gender="female",
        )
