from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.high_fidelity_eye_runtime_rebuild as rebuild


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fingerprint_authority(tmp_path: Path, *, package_sha: str, body_id: str, fingerprint_sha: str = "f" * 64):
    path = tmp_path / "fingerprint.json"
    path.write_text("{}\n", encoding="utf-8")
    value = {
        "fingerprintPath": str(path),
        "candidatePackageSha256": package_sha,
        "canonicalBodyId": body_id,
        "fingerprintSha256": fingerprint_sha,
        "reviewVrmSha256": "r" * 64,
        "fingerprint": {
            "eyeMetadata": {
                "eyeComponentReceiptSha256": "1" * 64,
                "eyeAppearanceReceiptSha256": "2" * 64,
                "canonicalEyeBakeSha256": "3" * 64,
                "targetModelFamily": "female",
            }
        },
        "eyesPromotionEligibilityVerified": True,
        "eyeComponentAuthority": False,
        "packageMutationPerformed": False,
        "eyesPromoted": False,
        "productionActivation": False,
    }
    return value, path


def test_prepare_rebuild_binds_exact_candidate_package_and_base_avatar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"exact-package")
    package_sha = _sha(package.read_bytes())
    avatar = b"exact-base-avatar"
    avatar_sha = _sha(avatar)
    body_id = "body-1"
    staging = tmp_path / "staging"
    staging.mkdir()
    fp, fp_path = _fingerprint_authority(tmp_path, package_sha=package_sha, body_id=body_id)
    base_receipt_path = tmp_path / "base-runtime.json"
    base_receipt_path.write_text("{}\n", encoding="utf-8")
    base_receipt = {
        "packageSha256": package_sha,
        "bodyId": body_id,
        "baseAvatarVrmSha256": avatar_sha,
    }

    monkeypatch.setattr(rebuild, "_fingerprint_authority", lambda *args, **kwargs: (fp, fp_path))
    monkeypatch.setattr(rebuild, "_package_avatar", lambda path: (avatar, body_id))
    monkeypatch.setattr(rebuild, "_base_runtime", lambda path: (base_receipt, tmp_path / "review.vrm", base_receipt_path, {}))

    value = rebuild.prepare_rebuild(
        "hfpreview-" + "1" * 32,
        package_path=package,
        base_runtime_dir=tmp_path,
        iris_candidate_dir=tmp_path,
        source_eye_appearance_dir=tmp_path,
        reviewed_runtime_dir=tmp_path,
        staging_dir=staging,
        bodyrig_revision="a" * 40,
    )

    assert Path(value["baseAvatarPath"]).read_bytes() == avatar
    assert value["candidatePackageSha256"] == package_sha
    assert value["baseAvatarVrmSha256"] == avatar_sha
    assert value["sourceFingerprintSha256"] == fp["fingerprintSha256"]
    assert value["eyeComponentAuthority"] is False
    assert value["packageMutationPerformed"] is False
    assert value["productionActivation"] is False

    with pytest.raises(rebuild.HighFidelityEyeRuntimeRebuildError, match="create-only"):
        rebuild.prepare_rebuild(
            "hfpreview-" + "1" * 32,
            package_path=package,
            base_runtime_dir=tmp_path,
            iris_candidate_dir=tmp_path,
            source_eye_appearance_dir=tmp_path,
            reviewed_runtime_dir=tmp_path,
            staging_dir=staging,
            bodyrig_revision="a" * 40,
        )


def test_prepare_rebuild_rejects_different_candidate_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package-a")
    staging = tmp_path / "staging"
    staging.mkdir()
    fp, fp_path = _fingerprint_authority(tmp_path, package_sha=_sha(b"package-b"), body_id="body-1")
    monkeypatch.setattr(rebuild, "_fingerprint_authority", lambda *args, **kwargs: (fp, fp_path))

    with pytest.raises(rebuild.HighFidelityEyeRuntimeRebuildError, match="candidate package differs"):
        rebuild.prepare_rebuild(
            "hfpreview-" + "2" * 32,
            package_path=package,
            base_runtime_dir=tmp_path,
            iris_candidate_dir=tmp_path,
            source_eye_appearance_dir=tmp_path,
            reviewed_runtime_dir=tmp_path,
            staging_dir=staging,
            bodyrig_revision="a" * 40,
        )


def test_finalize_rebuild_rejects_fingerprint_mismatch_without_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / rebuild.REVIEW_VRM_NAME).write_bytes(b"rebuilt-eye-vrm")
    (staging / rebuild.BRIDGE_RESULT_NAME).write_text("{}\n", encoding="utf-8")
    source_fp, fp_path = _fingerprint_authority(tmp_path, package_sha="p" * 64, body_id="body-1", fingerprint_sha="a" * 64)
    preparation = {
        "bodyrigRevision": "b" * 40,
        "canonicalBodyId": "body-1",
        "candidatePackageSha256": "p" * 64,
        "baseAvatarVrmSha256": "c" * 64,
    }
    bridge = {"reviewVrmSha256": _sha((staging / rebuild.REVIEW_VRM_NAME).read_bytes())}

    monkeypatch.setattr(rebuild, "read_preparation", lambda *args, **kwargs: preparation)
    monkeypatch.setattr(rebuild, "_fingerprint_authority", lambda *args, **kwargs: (source_fp, fp_path))
    monkeypatch.setattr(rebuild, "_bridge", lambda *args, **kwargs: bridge)
    monkeypatch.setattr(rebuild, "_assert_no_hair_runtime", lambda value: None)
    monkeypatch.setattr(
        rebuild,
        "semantic_eye_runtime_fingerprint",
        lambda value: {"fingerprintSha256": "b" * 64, "payload": source_fp["fingerprint"]},
    )

    with pytest.raises(rebuild.HighFidelityEyeRuntimeRebuildError, match="semantic fingerprint differs"):
        rebuild.finalize_rebuild(
            "hfpreview-" + "3" * 32,
            package_path=tmp_path / "candidate.mrbody",
            base_runtime_dir=tmp_path,
            iris_candidate_dir=tmp_path,
            source_eye_appearance_dir=tmp_path,
            reviewed_runtime_dir=tmp_path,
            staging_dir=staging,
            bodyrig_revision="b" * 40,
            bridge_script_sha256="d" * 64,
        )
    assert not (staging / rebuild.RECEIPT_NAME).exists()


def test_finalize_rebuild_records_only_non_materializing_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    prep_path = staging / rebuild.PREPARATION_NAME
    prep_path.write_text("{}\n", encoding="utf-8")
    vrm_path = staging / rebuild.REVIEW_VRM_NAME
    bridge_path = staging / rebuild.BRIDGE_RESULT_NAME
    vrm_path.write_bytes(b"rebuilt-eye-vrm")
    bridge_path.write_text("{}\n", encoding="utf-8")
    source_fp, fp_path = _fingerprint_authority(tmp_path, package_sha="e" * 64, body_id="body-1", fingerprint_sha="a" * 64)
    preparation = {
        "bodyrigRevision": "b" * 40,
        "canonicalBodyId": "body-1",
        "candidatePackageSha256": "e" * 64,
        "baseAvatarVrmSha256": "c" * 64,
    }
    bridge = {"reviewVrmSha256": _sha(vrm_path.read_bytes())}
    rebuilt_fp = {"fingerprintSha256": "a" * 64, "payload": source_fp["fingerprint"]}

    monkeypatch.setattr(rebuild, "read_preparation", lambda *args, **kwargs: preparation)
    monkeypatch.setattr(rebuild, "_fingerprint_authority", lambda *args, **kwargs: (source_fp, fp_path))
    monkeypatch.setattr(rebuild, "_bridge", lambda *args, **kwargs: bridge)
    monkeypatch.setattr(rebuild, "_assert_no_hair_runtime", lambda value: None)
    monkeypatch.setattr(rebuild, "semantic_eye_runtime_fingerprint", lambda value: rebuilt_fp)

    def fake_read(*args, **kwargs):
        receipt = json.loads((staging / rebuild.RECEIPT_NAME).read_text(encoding="utf-8"))
        return {**receipt, "rebuildReceiptPath": str(staging / rebuild.RECEIPT_NAME), "rebuiltVrmPath": str(vrm_path)}

    monkeypatch.setattr(rebuild, "read_rebuild", fake_read)
    value = rebuild.finalize_rebuild(
        "hfpreview-" + "4" * 32,
        package_path=tmp_path / "candidate.mrbody",
        base_runtime_dir=tmp_path,
        iris_candidate_dir=tmp_path,
        source_eye_appearance_dir=tmp_path,
        reviewed_runtime_dir=tmp_path,
        staging_dir=staging,
        bodyrig_revision="b" * 40,
        bridge_script_sha256="d" * 64,
    )

    assert value["fingerprintMatch"] is True
    assert value["sourceFingerprintSha256"] == value["rebuiltFingerprintSha256"] == "a" * 64
    assert value["sourceHairRuntimeImported"] is False
    assert value["eyeOnlyRuntimeVerified"] is True
    assert value["eyeComponentAuthority"] is False
    assert value["packageMutationPerformed"] is False
    assert value["eyesPromoted"] is False
    assert value["productionActivation"] is False
