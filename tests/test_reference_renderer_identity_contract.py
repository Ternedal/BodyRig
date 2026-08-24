from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / "reference-renderer"


def test_reference_renderer_identity_contract_matches_pinned_project() -> None:
    contract = json.loads((REFERENCE / "renderer-contract.json").read_text(encoding="utf-8"))
    assert contract == {
        "format": "bodyrig-reference-renderer-contract",
        "version": 1,
        "renderer_name": "BodyRig Reference Renderer",
        "renderer_version": "reference-v1/univrm-0.131.2",
        "unity_editor_version": "6000.3.13f1",
        "univrm_version": "0.131.2",
        "application_id": "dk.ternedal.bodyrig.reference",
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
    }

    project_version = (REFERENCE / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8")
    assert f"m_EditorVersion: {contract['unity_editor_version']}" in project_version

    manifest = json.loads((REFERENCE / "Packages" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"]["com.vrmc.gltf"].endswith(f"#v{contract['univrm_version']}")
    assert manifest["dependencies"]["com.vrmc.vrm"].endswith(f"#v{contract['univrm_version']}")


def test_physical_probe_wrappers_emit_canonical_renderer_identity() -> None:
    contract = json.loads((REFERENCE / "renderer-contract.json").read_text(encoding="utf-8"))
    windows = (REPO / "run-windows-renderer-probe.ps1").read_text(encoding="utf-8")
    quest = (REPO / "run-quest-renderer-probe.ps1").read_text(encoding="utf-8")

    for source in (windows, quest):
        assert contract["renderer_name"] in source
        assert contract["renderer_version"] in source


def test_reference_attestation_derives_identity_instead_of_asking_operator() -> None:
    source = (REPO / "record-reference-renderer-acceptance.ps1").read_text(encoding="utf-8")
    assert "reference-renderer\\renderer-contract.json" in source
    assert "active_renderer.name" in source
    assert "active_renderer.version" in source
    assert "RendererName = [string]$contract.renderer_name" in source
    assert "RendererVersion = [string]$contract.renderer_version" in source
    assert "QualityNote" in source
    assert "Resolve-EvidencePair" in source
    assert '"$Prefix-evidence"' in source
