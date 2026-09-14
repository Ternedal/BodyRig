from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.fidelity_component_gate as gate


def _meta(*, toenails: bool = False) -> dict[str, object]:
    value: dict[str, object] = {
        "format": gate.TOENAIL_FORMAT if toenails else gate.FINGERNAIL_FORMAT,
        "version": 1,
        "policyRevision": gate.TOENAIL_POLICY if toenails else gate.FINGERNAIL_POLICY,
        "nodeName": gate.TOENAIL_NODE if toenails else gate.FINGERNAIL_NODE,
        "meshName": gate.TOENAIL_MESH if toenails else gate.FINGERNAIL_MESH,
        "materialName": gate.TOENAIL_MATERIAL if toenails else gate.FINGERNAIL_MATERIAL,
        "skinIndex": 0,
        "plateCount": 10,
        "triangleCount": 20,
        "vertexCount": 60,
        "plateTriangleCounts": {f"plate-{index}": 2 for index in range(10)},
        "sourceGrounded": True,
        "additiveGeometryOnly": True,
        "geometryModified": True,
        "textureModified": False,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    if toenails:
        value["toeLandmarkAuthority"] = gate.TOENAIL_LANDMARK_AUTHORITY
        value["individualMiddleToeLandmarksObserved"] = False
    return value


def _document() -> dict[str, object]:
    return {
        "nodes": [
            {"name": gate.FINGERNAIL_NODE, "mesh": 0, "skin": 0},
            {"name": gate.TOENAIL_NODE, "mesh": 1, "skin": 0},
        ],
        "meshes": [
            {
                "name": gate.FINGERNAIL_MESH,
                "primitives": [{"attributes": {"POSITION": 0}, "material": 0}],
            },
            {
                "name": gate.TOENAIL_MESH,
                "primitives": [{"attributes": {"POSITION": 1}, "material": 1}],
            },
        ],
        "materials": [
            {
                "name": gate.FINGERNAIL_MATERIAL,
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            },
            {
                "name": gate.TOENAIL_MATERIAL,
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            },
        ],
        "scenes": [{"nodes": [0, 1]}],
        "extras": {
            "bodyrig": {
                gate.FINGERNAIL_FIELD: _meta(),
                gate.TOENAIL_FIELD: _meta(toenails=True),
            }
        },
    }


def _audit(package: Path) -> dict[str, object]:
    return {
        "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "canonical_body_id": "bodyid-test",
        "components": {name: "complete" for name in gate.REQUIRED_CORE_COMPONENTS},
        "high_fidelity_ready": True,
        "render_payloads": {name: {"present": True} for name in gate.REQUIRED_RENDER_PAYLOADS},
        "human_review_required": True,
        "production_ready": False,
    }


def _install_valid(monkeypatch: pytest.MonkeyPatch, package: Path, document: dict[str, object]) -> None:
    monkeypatch.setattr(gate, "audit_high_fidelity_package", lambda _path: _audit(package))
    monkeypatch.setattr(gate, "_avatar_document", lambda _path: document)


def test_gate_accepts_complete_concrete_component_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    document = _document()
    _install_valid(monkeypatch, package, document)

    result = gate.assess_package(package)

    assert result["full_fidelity_components_present"] is True
    assert result["human_visual_authority_required"] is True
    assert result["production_activation"] is False
    assert result["fingernails"]["plate_count"] == 10
    assert result["toenails"]["plate_count"] == 10


def test_gate_rejects_missing_concrete_hair_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    audit = _audit(package)
    audit["render_payloads"] = {
        name: {"present": True}
        for name in gate.REQUIRED_RENDER_PAYLOADS
        if name != "hair"
    }
    monkeypatch.setattr(gate, "audit_high_fidelity_package", lambda _path: audit)
    monkeypatch.setattr(gate, "_avatar_document", lambda _path: _document())

    with pytest.raises(gate.FidelityComponentGateError, match="hair"):
        gate.assess_package(package)


def test_gate_rejects_missing_fingernail_geometry_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    document = _document()
    del document["extras"]["bodyrig"][gate.FINGERNAIL_FIELD]  # type: ignore[index]
    _install_valid(monkeypatch, package, document)

    with pytest.raises(gate.FidelityComponentGateError, match="fingernails geometry authority is missing"):
        gate.assess_package(package)


def test_gate_rejects_false_middle_toe_source_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    document = _document()
    document["extras"]["bodyrig"][gate.TOENAIL_FIELD]["individualMiddleToeLandmarksObserved"] = True  # type: ignore[index]
    _install_valid(monkeypatch, package, document)

    with pytest.raises(gate.FidelityComponentGateError, match="toenail source-landmark authority is invalid"):
        gate.assess_package(package)
