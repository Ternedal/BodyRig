from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.source_hair_body_binding as binding


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _authority() -> dict[str, object]:
    return {
        "format": "bodyrig-sith-body-geometry-authority",
        "version": 1,
        "method": "exact-sith-reconstruction-bytes-v1",
        "reconstructionSha256": "a" * 64,
        "fittedDonorObjSha256": "b" * 64,
        "fitParamsSha256": "c" * 64,
        "sourceMeshSha256": "d" * 64,
        "sourceMaterialSha256": "e" * 64,
        "sourceTextureSha256": "f" * 64,
        "sourceTextureName": "hair.png",
        "exactByteBinding": True,
        "hairCandidateBindingEligible": True,
        "productionActivation": False,
    }


def _candidate(tmp_path: Path) -> Path:
    root = tmp_path / "hair"
    root.mkdir()
    hair_obj = b"v 0 0 0\n" * 40
    material = b"newmtl hair\nmap_Kd hair.png\n"
    texture = b"\x89PNG\r\n\x1a\nhair-fixture"
    (root / "hair_source.obj").write_bytes(hair_obj)
    (root / "000.mtl").write_bytes(material)
    (root / "hair.png").write_bytes(texture)
    receipt = {
        "format": "bodyrig-source-hair-candidate",
        "version": 1,
        "method": "retained-sith-connected-head-shell-v1",
        "sourceReconstructionSha256": "a" * 64,
        "sourceMeshSha256": "d" * 64,
        "sourceMaterialSha256": "e" * 64,
        "sourceTextureSha256": "f" * 64,
        "donorObjSha256": "b" * 64,
        "hairObjSha256": _sha(hair_obj),
        "hairMaterialSha256": _sha(material),
        "hairTextureSha256": _sha(texture),
        "selectedFaceCount": 40,
        "selectedVertexCount": 30,
        "seedFaceCount": 8,
        "bodyHeight": 1.8,
        "headSearchRadius": 0.18,
        "sourceToDonorDistanceP50": 0.03,
        "sourceToDonorDistanceP95": 0.04,
        "sourceToDonorDistanceMax": 0.05,
        "minimumBodyHeightRatio": 0.72,
        "maximumBodyHeightRatio": 0.98,
        "sourceDerived": True,
        "generativeGeometry": False,
        "bodyTopologyModified": False,
        "candidateBinding": "head-accessory-review-only",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    (root / "source-hair-candidate.json").write_text(json.dumps(receipt), encoding="utf-8")
    return root


class _Archive:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, name: str) -> bytes:
        assert name == "avatar.vrm"
        return b"avatar-vrm-fixture"


def _patch_body(monkeypatch) -> None:
    monkeypatch.setattr(
        binding,
        "validate_package",
        lambda _path: SimpleNamespace(manifest={"id": "bodyid-1234567890abcdef12345678"}),
    )
    monkeypatch.setattr(binding.zipfile, "ZipFile", lambda *_args, **_kwargs: _Archive())
    monkeypatch.setattr(binding, "read_sith_body_geometry_authority", lambda _avatar: _authority())


def test_build_binding_requires_five_exact_body_source_links(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package-fixture")
    candidate = _candidate(tmp_path)
    _patch_body(monkeypatch)

    value = binding.build_binding(package, candidate)

    assert value["bodyId"] == "bodyid-1234567890abcdef12345678"
    assert value["packageSha256"] == _sha(b"package-fixture")
    assert value["avatarVrmSha256"] == _sha(b"avatar-vrm-fixture")
    assert value["bindingStatus"] == "exact-source-and-donor-match"
    assert value["runtimeIntegrationRequired"] is True
    assert value["physicalSilhouetteReviewRequired"] is True
    assert value["comparisonOnly"] is True
    assert value["humanReviewRequired"] is True
    assert value["productionActivation"] is False


@pytest.mark.parametrize(
    ("candidate_field", "body_field"),
    [
        ("sourceReconstructionSha256", "reconstructionSha256"),
        ("donorObjSha256", "fittedDonorObjSha256"),
        ("sourceMeshSha256", "sourceMeshSha256"),
        ("sourceMaterialSha256", "sourceMaterialSha256"),
        ("sourceTextureSha256", "sourceTextureSha256"),
    ],
)
def test_build_binding_rejects_each_body_source_mismatch(
    monkeypatch,
    tmp_path: Path,
    candidate_field: str,
    body_field: str,
) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package-fixture")
    candidate = _candidate(tmp_path)
    candidate_path = candidate / "source-hair-candidate.json"
    receipt = json.loads(candidate_path.read_text(encoding="utf-8"))
    receipt[candidate_field] = "9" * 64
    candidate_path.write_text(json.dumps(receipt), encoding="utf-8")
    _patch_body(monkeypatch)

    with pytest.raises(binding.SourceHairBodyBindingError, match=candidate_field):
        binding.build_binding(package, candidate)


def test_candidate_rehashes_hair_bytes(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package-fixture")
    candidate = _candidate(tmp_path)
    (candidate / "hair_source.obj").write_bytes(b"tampered")
    _patch_body(monkeypatch)

    with pytest.raises(binding.SourceHairBodyBindingError, match="hairObjSha256"):
        binding.build_binding(package, candidate)


def test_candidate_rejects_unsafe_texture_reference(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package-fixture")
    candidate = _candidate(tmp_path)
    material = b"newmtl hair\nmap_Kd ../hair.png\n"
    (candidate / "000.mtl").write_bytes(material)
    receipt_path = candidate / "source-hair-candidate.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["hairMaterialSha256"] = _sha(material)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    _patch_body(monkeypatch)

    with pytest.raises(binding.SourceHairBodyBindingError, match="safe leaf filename"):
        binding.build_binding(package, candidate)


def test_write_binding_is_create_only(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "body.mrbody"
    package.write_bytes(b"package-fixture")
    candidate = _candidate(tmp_path)
    _patch_body(monkeypatch)
    output = tmp_path / "hair-body-binding.json"

    first = binding.write_binding(package, candidate, output)
    original = output.read_bytes()
    assert first["productionActivation"] is False

    with pytest.raises(binding.SourceHairBodyBindingError, match="already exists"):
        binding.write_binding(package, candidate, output)
    assert output.read_bytes() == original
