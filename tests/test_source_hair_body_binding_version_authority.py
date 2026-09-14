from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import source_hair_body_binding as binding


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_dir(tmp_path: Path, *, version: Any) -> Path:
    root = tmp_path / "candidate"
    root.mkdir()
    hair_obj = root / "hair_source.obj"
    material = root / "000.mtl"
    texture = root / "source.png"
    hair_obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    material.write_text("newmtl hair\nmap_Kd source.png\n", encoding="utf-8")
    texture.write_bytes(b"\x89PNG\r\n\x1a\nsource-hair")

    receipt = {
        "format": binding.CANDIDATE_FORMAT,
        "version": version,
        "method": "retained-sith-connected-head-shell-v2",
        "sourceReconstructionSha256": "1" * 64,
        "sourceMeshSha256": "2" * 64,
        "sourceMaterialSha256": "3" * 64,
        "sourceTextureSha256": "4" * 64,
        "donorObjSha256": "5" * 64,
        "hairObjSha256": _sha(hair_obj),
        "hairMaterialSha256": _sha(material),
        "hairTextureSha256": _sha(texture),
        "selectedFaceCount": 40,
        "selectedVertexCount": 60,
        "seedFaceCount": 20,
        "selectionMode": "strict-shell",
        "minimumDistanceBodyRatio": 0.008,
        "seedDistanceBodyRatio": 0.006,
        "minimumYBodyRatio": 0.60,
        "seedYBodyRatio": 0.79,
        "headFootprintSpanBodyRatio": 0.10,
        "verticalSpanBodyRatio": 0.05,
        "bodyHeight": 1.75,
        "headSearchRadius": 0.25,
        "sourceToDonorDistanceP50": 0.001,
        "sourceToDonorDistanceP95": 0.002,
        "sourceToDonorDistanceMax": 0.003,
        "minimumBodyHeightRatio": 0.60,
        "maximumBodyHeightRatio": 1.05,
        "sourceDerived": True,
        "generativeGeometry": False,
        "bodyTopologyModified": False,
        "candidateBinding": "head-accessory-review-only",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    (root / "source-hair-candidate.json").write_text(
        json.dumps(receipt, sort_keys=True), encoding="utf-8"
    )
    return root


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_candidate_rejects_boolean_non_numeric_and_wrong_v1(tmp_path: Path, version: Any) -> None:
    root = _candidate_dir(tmp_path, version=version)

    with pytest.raises(binding.SourceHairBodyBindingError, match="candidate format/version mismatch"):
        binding._candidate(root)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_candidate_preserves_numeric_v1_and_review_only_authority(tmp_path: Path, version: Any) -> None:
    root = _candidate_dir(tmp_path, version=version)

    receipt, receipt_path, hair_obj, material, texture = binding._candidate(root)

    assert receipt["version"] == version
    assert receipt["sourceDerived"] is True
    assert receipt["comparisonOnly"] is True
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False
    assert receipt_path.name == "source-hair-candidate.json"
    assert hair_obj.name == "hair_source.obj"
    assert material.name == "000.mtl"
    assert texture.name == "source.png"
