from __future__ import annotations

from pathlib import Path

from bodyrig.high_fidelity_eye_runtime_fingerprint import _v1 as fingerprint_v1
from bodyrig.high_fidelity_eye_runtime_rebuild import _is_version as rebuild_version
from bodyrig.high_fidelity_eyes_promotion_eligibility import _v1 as eligibility_v1


ROOT = Path(__file__).resolve().parents[1]
ELIGIBILITY = ROOT / "bodyrig" / "high_fidelity_eyes_promotion_eligibility.py"
FINGERPRINT = ROOT / "bodyrig" / "high_fidelity_eye_runtime_fingerprint.py"
REBUILD = ROOT / "bodyrig" / "high_fidelity_eye_runtime_rebuild.py"
IRIS_RUNTIME = ROOT / "bodyrig" / "source_iris_review_runtime.py"


def test_eyes_pre_materialization_v1_runtime_semantics() -> None:
    for predicate in (eligibility_v1, fingerprint_v1):
        assert predicate(1)
        assert predicate(1.0)
        assert not predicate(True)
        assert not predicate(False)
        assert not predicate("1")
        assert not predicate(None)
        assert not predicate(2)

    for expected in (1,):
        assert rebuild_version(1, expected)
        assert rebuild_version(1.0, expected)
        assert not rebuild_version(True, expected)
        assert not rebuild_version(False, expected)
        assert not rebuild_version("1", expected)
        assert not rebuild_version(None, expected)
        assert not rebuild_version(2, expected)


def test_eyes_eligibility_receipt_uses_bool_safe_v1() -> None:
    source = ELIGIBILITY.read_text(encoding="utf-8")
    assert "def _v1(value: Any) -> bool:" in source
    assert "return not isinstance(value, bool) and value == VERSION" in source
    assert 'not _v1(value.get("version"))' in source
    assert 'value.get("version") != VERSION' not in source


def test_eye_fingerprint_metadata_and_receipt_use_bool_safe_v1() -> None:
    source = FINGERPRINT.read_text(encoding="utf-8")
    assert "def _v1(value: Any) -> bool:" in source
    assert "return not isinstance(value, bool) and value == VERSION" in source
    assert 'not _v1(eye.get("version"))' in source
    assert 'not _v1(value.get("version"))' in source
    assert 'eye.get("version") != 1' not in source
    assert 'value.get("version") != VERSION' not in source


def test_eye_rebuild_all_active_readers_use_bool_safe_versions() -> None:
    source = REBUILD.read_text(encoding="utf-8")
    assert "def _is_version(value: Any, expected: int) -> bool:" in source
    assert "return not isinstance(value, bool) and value == expected" in source
    assert 'not _is_version(value.get("version"), PREPARATION_VERSION)' in source
    assert 'not _is_version(value.get("version"), BRIDGE_VERSION)' in source
    assert 'not _is_version(value.get("version"), VERSION)' in source
    assert 'value.get("version") != PREPARATION_VERSION' not in source
    assert 'value.get("version") != BRIDGE_VERSION' not in source
    assert 'value.get("version") != VERSION' not in source


def test_iris_review_runtime_was_already_bool_safe_and_remains_unchanged_in_shape() -> None:
    source = IRIS_RUNTIME.read_text(encoding="utf-8")
    assert "def _is_version(value: Any, expected: int) -> bool:" in source
    assert "return not isinstance(value, bool) and value == expected" in source
    assert 'not _is_version(receipt.get("version"), BASE_RUNTIME_VERSION)' in source
    assert 'not _is_version(eye.get("version"), EYE_METADATA_VERSION)' in source
    assert 'not _is_version(value.get("version"), VERSION)' in source


def test_eyes_chain_preserves_non_materializing_and_exact_runtime_boundaries() -> None:
    eligibility = ELIGIBILITY.read_text(encoding="utf-8")
    fingerprint = FINGERPRINT.read_text(encoding="utf-8")
    rebuild = REBUILD.read_text(encoding="utf-8")

    for marker in (
        'reviewed.get("baseReviewVrmSha256") != review_vrm_sha',
        'reviewed.get("reviewedVrmSha256") != review_vrm_sha',
        'value.get("eyesPromotionEligible") is not True',
        'value.get("eyeComponentAuthority") is not False',
        'value.get("packageMutationPerformed") is not False',
        'value.get("eyesPromoted") is not False',
        'value.get("productionActivation") is not False',
    ):
        assert marker in eligibility

    for marker in (
        'reviewed.get("reviewedVrmSha256") != review_vrm_sha',
        '_sha256_file(reviewed_vrm_path) != review_vrm_sha',
        'metadata["canonicalEyeBakeSha256"] != source_image_sha',
        'value.get("eyeComponentAuthority") is not False',
        'value.get("packageMutationPerformed") is not False',
        'value.get("eyesPromoted") is not False',
        'value.get("productionActivation") is not False',
    ):
        assert marker in fingerprint

    for marker in (
        'rebuilt eye-only VRM imported hair runtime metadata',
        'rebuilt eye-only VRM imported source-hair runtime geometry',
        'rebuilt.get("fingerprintSha256") != source_sha',
        'rebuilt.get("payload") != source_fingerprint.get("fingerprint")',
        'value.get("sourceHairRuntimeImported") is not False',
        'value.get("eyeComponentAuthority") is not False',
        'value.get("packageMutationPerformed") is not False',
        'value.get("eyesPromoted") is not False',
        'value.get("productionActivation") is not False',
    ):
        assert marker in rebuild
