import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "reference-renderer" / "Assets" / "BodyRig"


def test_runtime_assembly_explicitly_references_univrm_non_auto_dependency() -> None:
    runtime = json.loads(
        (ASSETS / "BodyRig.ReferenceRenderer.Runtime.asmdef").read_text(encoding="utf-8")
    )

    assert runtime["name"] == "BodyRig.ReferenceRenderer.Runtime"
    assert runtime["autoReferenced"] is True
    assert set(runtime["references"]) == {
        "UniGLTF",
        "UniGLTF.Utils",
        "VRM10",
        "Unity.XR.Management",
        "Unity.XR.OpenXR",
    }
    assert runtime["includePlatforms"] == []


def test_editor_build_isolated_from_runtime_assembly() -> None:
    editor = json.loads(
        (ASSETS / "Editor" / "BodyRig.ReferenceRenderer.Editor.asmdef").read_text(encoding="utf-8")
    )

    assert editor["name"] == "BodyRig.ReferenceRenderer.Editor"
    assert set(editor["references"]) == {
        "BodyRig.ReferenceRenderer.Runtime",
        "Unity.XR.Management",
        "Unity.XR.Management.Editor",
        "Unity.XR.OpenXR",
        "Unity.XR.OpenXR.Editor",
    }
    assert editor["includePlatforms"] == ["Editor"]


def test_quest2_runtime_probe_xr_namespaces_have_direct_assembly_authority() -> None:
    source = (ASSETS / "BodyRigP3Quest2Probe.cs").read_text(encoding="utf-8")
    runtime = json.loads(
        (ASSETS / "BodyRig.ReferenceRenderer.Runtime.asmdef").read_text(encoding="utf-8")
    )
    assert "using UnityEngine.XR.Management;" in source
    assert "using UnityEngine.XR.OpenXR;" in source
    assert "Unity.XR.Management" in runtime["references"]
    assert "Unity.XR.OpenXR" in runtime["references"]


def test_reference_build_xr_editor_namespaces_have_direct_assembly_authority() -> None:
    source = (ASSETS / "Editor" / "BodyRigReferenceBuild.cs").read_text(encoding="utf-8")
    editor = json.loads(
        (ASSETS / "Editor" / "BodyRig.ReferenceRenderer.Editor.asmdef").read_text(encoding="utf-8")
    )
    assert "using UnityEditor.XR.Management;" in source
    assert "using UnityEditor.XR.Management.Metadata;" in source
    assert "using UnityEngine.XR.Management;" in source
    assert "using UnityEngine.XR.OpenXR;" in source
    for assembly in (
        "Unity.XR.Management",
        "Unity.XR.Management.Editor",
        "Unity.XR.OpenXR",
        "Unity.XR.OpenXR.Editor",
    ):
        assert assembly in editor["references"]
