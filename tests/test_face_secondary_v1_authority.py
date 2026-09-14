from __future__ import annotations

from pathlib import Path

from bodyrig.high_fidelity_face_secondary_preview import _is_version as preview_version
from bodyrig.high_fidelity_face_secondary_promotion import _is_version as promotion_version
from bodyrig.high_fidelity_face_secondary_review import _is_version as review_version
from bodyrig.high_fidelity_face_secondary_runtime import _is_version as runtime_version


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "bodyrig" / "high_fidelity_face_secondary_runtime.py"
PREVIEW = ROOT / "bodyrig" / "high_fidelity_face_secondary_preview.py"
REVIEW = ROOT / "bodyrig" / "high_fidelity_face_secondary_review.py"
PROMOTION = ROOT / "bodyrig" / "high_fidelity_face_secondary_promotion.py"


def test_face_secondary_v1_runtime_semantics() -> None:
    for predicate in (runtime_version, preview_version, review_version, promotion_version):
        assert predicate(1, 1)
        assert predicate(1.0, 1)
        assert not predicate(True, 1)
        assert not predicate(False, 1)
        assert not predicate("1", 1)
        assert not predicate(None, 1)
        assert not predicate(2, 1)


def test_runtime_uses_bool_safe_eye_receipt_and_embedded_metadata_versions() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert 'not _is_version(eye.get("version"), 1)' in source
    assert 'not _is_version(value.get("version"), VERSION)' in source
    assert 'embedded.get("format") != REVIEW_METADATA_FORMAT' in source
    assert 'not _is_version(embedded.get("version"), VERSION)' in source
    assert 'embedded.get("policyRevision") != POLICY_REVISION' in source
    for marker in (
        'embedded.get("sourcePackageSha256") != value.get("sourcePackageSha256")',
        'embedded.get("sourceAvatarSha256") != value.get("sourceAvatarSha256")',
        'embedded.get("appearanceTransferSha256") != value.get("appearanceTransferSha256")',
        'embedded.get("eyePromotionSha256") != value.get("eyePromotionSha256")',
        'embedded.get("canonicalBodyId") != value.get("canonicalBodyId")',
        'embedded.get("bodyrigRevision") != value.get("bodyrigRevision")',
        'embedded.get("sourceDerivedIdentitySynthesis") is not False',
        'embedded.get("generativeIdentitySynthesis") is not False',
        'embedded.get("productionActivation") is not False',
    ):
        assert marker in source
    assert 'eye.get("version") != 1' not in source
    assert 'value.get("version") != VERSION' not in source


def test_preview_all_external_v1_authorities_are_bool_safe() -> None:
    source = PREVIEW.read_text(encoding="utf-8")
    for marker in (
        'not _is_version(value.get("version"), VERSION)',
        'not _is_version(comparison.get("version"), 1)',
        'not _is_version(manifest.get("version"), 1)',
        'not _is_version(value.get("version"), PREVIEW_VERSION)',
    ):
        assert marker in source
    assert 'comparison.get("version") != 1' not in source
    assert 'manifest.get("version") != 1' not in source
    for marker in (
        'comparison.get("physical_acceptance_authority") is not False',
        'comparison.get("comparison_only") is not True',
        'comparison.get("production_activation") is not False',
        'manifest.get("package_sha256") != prep["comparisonPackageSha256"]',
        'value.get("physicalAcceptanceAuthority") is not False',
        'value.get("packagePromotionAuthority") is not False',
        'value.get("productionActivation") is not False',
    ):
        assert marker in source


def test_human_review_receipt_v1_is_bool_safe_without_changing_human_gate() -> None:
    source = REVIEW.read_text(encoding="utf-8")
    assert 'not _is_version(value.get("version"), VERSION)' in source
    assert 'value.get("version") != VERSION' not in source
    for marker in (
        'normalized.get(field) is not True',
        'value.get("humanReviewComplete") is not True',
        'value.get("faceSecondaryPromotionEligible") is not True',
        'value.get("faceSecondaryComponentAuthority") is not False',
        'value.get("packageMutationPerformed") is not False',
        'value.get("productionActivation") is not False',
    ):
        assert marker in source


def test_promotion_review_receipt_and_embedded_v1_authorities_are_bool_safe() -> None:
    source = PROMOTION.read_text(encoding="utf-8")
    assert 'not _is_version(review_meta.get("version"), 1)' in source
    assert 'not _is_version(value.get("version"), VERSION)' in source
    assert 'not _is_version(embedded.get("version"), VERSION)' in source
    assert 'embedded.get("policyRevision") != POLICY_REVISION' in source
    assert 'value.get("version") != VERSION' not in source
    assert 'embedded.get("version") != VERSION' not in source
    for marker in (
        'review.get("sourceRuntimeReceiptSha256") != _sha256_file(Path(runtime["receiptPath"]))',
        'review.get("sourceReviewVrmSha256") != _sha256_bytes(review_vrm)',
        'embedded.get("sourcePackageSha256") != source_sha',
        'embedded.get("humanReviewReceiptSha256") != expected_exact["humanReviewReceiptSha256"]',
        'value.get("sourceDerivedIdentitySynthesis") is not False',
        'value.get("generativeIdentitySynthesis") is not False',
        'value.get("productionActivation") is not False',
        'audit["production_ready"] is not False',
    ):
        assert marker in source
