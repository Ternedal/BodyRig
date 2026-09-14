from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.source_hair_review_runtime as runtime


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bridge_value(version: object = 1) -> dict[str, object]:
    return {
        "format": runtime.BRIDGE_FORMAT,
        "version": version,
        "baseAvatarVrmSha256": "a" * 64,
        "sourceHairBodyBindingSha256": "b" * 64,
        "reviewVrmSha256": "c" * 64,
        "targetModelFamily": "female",
        "skinIndex": 0,
        "hairMeshIndex": 1,
        "hairVertexCount": 3,
        "hairFaceCount": 1,
        "fitMax": 0.01,
        "fitRms": 0.005,
        "nearestDonorDistanceP95": 0.01,
        "nearestDonorDistanceMax": 0.02,
        "bodyprintGeometryReplayApplied": False,
        "bodyprintMaxJointDelta": 0.0,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "productionActivation": False,
    }


def _runtime_document(version: object = 1) -> dict[str, object]:
    return {
        "extras": {
            "bodyrig": {
                "hairReviewRuntime": {
                    "format": runtime.METADATA_FORMAT,
                    "version": version,
                    "baseAvatarVrmSha256": "a" * 64,
                    "sourceHairBodyBindingSha256": "b" * 64,
                    "hairCandidateReceiptSha256": "c" * 64,
                    "hairObjSha256": "d" * 64,
                    "hairTextureSha256": "e" * 64,
                    "targetModelFamily": "female",
                    "skinIndex": 0,
                    "bodyprintGeometryReplayApplied": False,
                    "physicalSilhouetteReviewRequired": True,
                    "comparisonOnly": True,
                    "humanReviewRequired": True,
                    "productionActivation": False,
                }
            }
        }
    }


@pytest.mark.parametrize("version", (True, False, "1", None, 2))
def test_bridge_result_rejects_boolean_or_non_numeric_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "source-hair-review-bridge.json"
    path.write_text(json.dumps(_bridge_value(version)), encoding="utf-8")

    with pytest.raises(runtime.SourceHairReviewRuntimeError, match="fields/format do not match v1"):
        runtime._bridge_result(path)


@pytest.mark.parametrize("version", (1, 1.0))
def test_bridge_result_accepts_numeric_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "source-hair-review-bridge.json"
    path.write_text(json.dumps(_bridge_value(version)), encoding="utf-8")

    parsed = runtime._bridge_result(path)
    assert parsed["version"] == version
    assert parsed["comparisonOnly"] is True
    assert parsed["humanReviewRequired"] is True
    assert parsed["productionActivation"] is False


@pytest.mark.parametrize("version", (True, False, "1", None, 2))
def test_runtime_metadata_rejects_boolean_or_non_numeric_v1(version: object) -> None:
    with pytest.raises(runtime.SourceHairReviewRuntimeError, match="metadata format/version mismatch"):
        runtime._runtime_metadata(_runtime_document(version))


@pytest.mark.parametrize("version", (1, 1.0))
def test_runtime_metadata_accepts_numeric_v1(version: object) -> None:
    parsed = runtime._runtime_metadata(_runtime_document(version))
    assert parsed["version"] == version
    assert parsed["comparisonOnly"] is True
    assert parsed["humanReviewRequired"] is True
    assert parsed["productionActivation"] is False


def _stage_binding(tmp_path: Path, version: object) -> tuple[Path, dict[str, object]]:
    staging = tmp_path / "staging"
    staging.mkdir()
    avatar = b"avatar"
    fresh = {
        "format": "bodyrig-source-hair-body-binding",
        "version": 1,
        "avatarVrmSha256": _sha(avatar),
    }
    persisted = dict(fresh)
    persisted["version"] = version
    (staging / "source-hair-body-binding.json").write_text(json.dumps(persisted), encoding="utf-8")
    (staging / "base-avatar.vrm").write_bytes(avatar)
    (staging / "source-hair-review-bridge.json").write_text("{}", encoding="utf-8")
    (staging / "source-hair-review.vrm").write_bytes(b"review")
    return staging, fresh


def test_finalize_rejects_boolean_v1_before_dict_equality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging, fresh = _stage_binding(tmp_path, True)
    monkeypatch.setattr(runtime, "build_binding", lambda *_args, **_kwargs: fresh)

    with pytest.raises(runtime.SourceHairReviewRuntimeError, match="binding format/version mismatch"):
        runtime.finalize(
            package_path=tmp_path / "body.mrbody",
            candidate_dir=tmp_path / "candidate",
            staging_dir=staging,
            bodyrig_revision="a" * 40,
            bridge_script_sha256="b" * 64,
        )


def test_finalize_accepts_numeric_float_v1_before_exact_binding_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging, fresh = _stage_binding(tmp_path, 1.0)
    monkeypatch.setattr(runtime, "build_binding", lambda *_args, **_kwargs: fresh)

    class ReachedBridge(RuntimeError):
        pass

    def reached_bridge(_path: Path):
        raise ReachedBridge("numeric-v1 passed persisted binding gate")

    monkeypatch.setattr(runtime, "_bridge_result", reached_bridge)
    with pytest.raises(ReachedBridge, match="numeric-v1 passed"):
        runtime.finalize(
            package_path=tmp_path / "body.mrbody",
            candidate_dir=tmp_path / "candidate",
            staging_dir=staging,
            bodyrig_revision="a" * 40,
            bridge_script_sha256="b" * 64,
        )
