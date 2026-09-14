from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.high_fidelity_eye_promotion as promotion


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "bodyrig" / "high_fidelity_eye_promotion.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
_ABSENT = object()


def _components(*, hair: str = "missing", eyes: str = "partial") -> dict[str, object]:
    states = {
        "body_anatomy": "complete",
        "skin_appearance": "partial",
        "hair": hair,
        "eyes": eyes,
        "face_secondary": "missing",
    }
    blockers = [name for name, state in states.items() if state != "complete"]
    return {
        "format": "bodyrig-avatar-fidelity-components",
        "version": 1,
        "components": states,
        "highFidelityReady": False,
        "blockers": blockers,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def _anatomy(source_sha: str, *, version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-body-anatomy-promotion",
        "version": version,
        "policyRevision": "bodyrig-high-fidelity-anatomy-promotion-v1",
        "previewJobId": "hfpreview-" + "1" * 32,
        "componentReviewSha256": "1" * 64,
        "sourcePackageSha256": source_sha,
        "anatomyGateSha256": "2" * 64,
        "bodyrigRevision": "a" * 40,
        "targetFamily": "female",
        "component": "body_anatomy",
        "productionActivation": False,
    }


def _hair(source_sha: str, *, version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-hair-promotion",
        "version": version,
        "policyRevision": "bodyrig-high-fidelity-hair-promotion-v1",
        "previewJobId": "hfpreview-" + "1" * 32,
        "sourceBodyRigRevision": "a" * 40,
        "promotionBodyRigRevision": "b" * 40,
        "targetFamily": "female",
        "sourceCandidatePackageSha256": source_sha,
        "anatomyPromotedPackageSha256": "3" * 64,
        "anatomyPromotionReceiptSha256": "4" * 64,
        "hairDeformationReviewSha256": "5" * 64,
        "combinedBridgeResultSha256": "6" * 64,
        "rebuiltHairBridgeSha256": "7" * 64,
        "rebuiltHairRuntimeReceiptSha256": "8" * 64,
        "rebuiltHairReviewVrmSha256": "9" * 64,
        "component": "hair",
        "eyesImported": False,
        "productionActivation": False,
    }


def _destination(source_sha: str, *, anatomy_version: object = 1, hair_version: object = _ABSENT) -> dict[str, object]:
    has_hair = hair_version is not _ABSENT
    bodyrig: dict[str, object] = {
        "fidelityComponents": _components(hair="complete" if has_hair else "missing"),
        "bodyAnatomyPromotion": _anatomy(source_sha, version=anatomy_version),
    }
    if has_hair:
        bodyrig["hairPromotion"] = _hair(source_sha, version=hair_version)
    return {"extras": {"bodyrig": bodyrig}, "nodes": [], "materials": [], "images": []}


def test_v1_predicate_accepts_only_numeric_v1() -> None:
    assert promotion._v1(1)
    assert promotion._v1(1.0)
    assert not promotion._v1(True)
    assert not promotion._v1(False)
    assert not promotion._v1("1")
    assert not promotion._v1(None)
    assert not promotion._v1(2)


@pytest.mark.parametrize("bad", [True, False, "1", None, 2])
def test_destination_lineage_rejects_non_numeric_v1_anatomy(bad: object) -> None:
    source_sha = "a" * 64
    with pytest.raises(promotion.HighFidelityEyePromotionError, match="anatomy promotion"):
        promotion._assert_destination_lineage(
            _destination(source_sha, anatomy_version=bad),
            source_candidate_sha=source_sha,
            canonical_body_id="body-1",
        )


@pytest.mark.parametrize("bad", [True, False, "1", None, 2])
def test_destination_lineage_rejects_non_numeric_v1_hair(bad: object) -> None:
    source_sha = "a" * 64
    with pytest.raises(promotion.HighFidelityEyePromotionError, match="hair promotion"):
        promotion._assert_destination_lineage(
            _destination(source_sha, hair_version=bad),
            source_candidate_sha=source_sha,
            canonical_body_id="body-1",
        )


def test_eye_promotion_all_four_v1_readers_use_bool_safe_predicate() -> None:
    assert "def _v1(value: Any) -> bool:" in SOURCE
    assert "return not isinstance(value, bool) and value == VERSION" in SOURCE
    assert 'not _v1(anatomy.get("version"))' in SOURCE
    assert 'not _v1(hair.get("version"))' in SOURCE
    assert 'not _v1(value.get("version"))' in SOURCE
    assert 'not _v1(embedded.get("version"))' in SOURCE
    assert 'anatomy.get("version") != 1' not in SOURCE
    assert 'hair.get("version") != 1' not in SOURCE
    assert 'value.get("version") != VERSION' not in SOURCE
    assert 'embedded.get("version") != VERSION' not in SOURCE


def test_eye_promotion_preserves_exact_materialization_boundaries() -> None:
    for marker in (
        'anatomy.get("sourcePackageSha256") != source_candidate_sha',
        'hair.get("sourceCandidatePackageSha256") != source_candidate_sha',
        'hair.get("eyesImported") is not False',
        'rebuild.get("rebuiltFingerprintSha256") != source_fingerprint_sha',
        'graft_fingerprint.get("fingerprintSha256") != source_fingerprint_sha',
        'final_fingerprint.get("fingerprintSha256") != source_fingerprint_sha',
        'audit["components"].get("eyes") != "complete"',
        'audit["production_ready"] is not False',
        '"sourceHairRuntimeImported": False',
        '"productionActivation": False',
        'embedded != expected_embedded',
    ):
        assert marker in SOURCE
