from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.source_hair_body_binding as binding


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate(tmp_path: Path, *, generative: bool = True) -> Path:
    root = tmp_path / "hair-cards"
    root.mkdir()
    hair_obj = b"mtllib 000.mtl\nv 0 0 0\nvt 0 0\nf 1/1 1/1 1/1\n"
    material = b"newmtl hair\nmap_Kd hair.png\n"
    texture = b"\x89PNG\r\n\x1a\nsource-guided-hair-cards"
    (root / "hair_source.obj").write_bytes(hair_obj)
    (root / "000.mtl").write_bytes(material)
    (root / "hair.png").write_bytes(texture)
    receipt = {
        "format": "bodyrig-source-hair-candidate",
        "version": 1,
        "method": "retained-sith-source-guided-hair-cards-v1",
        "sourceReconstructionSha256": "a" * 64,
        "sourceMeshSha256": "d" * 64,
        "sourceMaterialSha256": "e" * 64,
        "sourceTextureSha256": "f" * 64,
        "donorObjSha256": "b" * 64,
        "hairObjSha256": _sha(hair_obj),
        "hairMaterialSha256": _sha(material),
        "hairTextureSha256": _sha(texture),
        "selectedFaceCount": 576,
        "selectedVertexCount": 720,
        "seedFaceCount": 32,
        "selectionMode": "strict-shell",
        "minimumDistanceBodyRatio": 0.008,
        "seedDistanceBodyRatio": 0.006,
        "minimumYBodyRatio": 0.60,
        "seedYBodyRatio": 0.79,
        "headFootprintSpanBodyRatio": 0.10,
        "verticalSpanBodyRatio": 0.08,
        "bodyHeight": 1.8,
        "headSearchRadius": 0.18,
        "sourceToDonorDistanceP50": 0.02,
        "sourceToDonorDistanceP95": 0.03,
        "sourceToDonorDistanceMax": 0.05,
        "minimumBodyHeightRatio": 0.72,
        "maximumBodyHeightRatio": 0.98,
        "sourceDerived": True,
        "generativeGeometry": generative,
        "bodyTopologyModified": False,
        "candidateBinding": "head-accessory-review-only",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    (root / "source-hair-candidate.json").write_text(json.dumps(receipt), encoding="utf-8")
    return root


def test_binding_accepts_source_guided_cards_only_as_review_geometry(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)

    receipt, _receipt_path, _obj, _material, _texture = binding._candidate(candidate)

    assert receipt["method"] == "retained-sith-source-guided-hair-cards-v1"
    assert receipt["generativeGeometry"] is True
    assert receipt["comparisonOnly"] is True
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False


def test_binding_rejects_cards_that_hide_generated_geometry_state(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, generative=False)

    with pytest.raises(binding.SourceHairBodyBindingError, match="authority boundary"):
        binding._candidate(candidate)
