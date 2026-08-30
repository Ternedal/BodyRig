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
    assert set(runtime["references"]) == {"UniGLTF", "UniGLTF.Utils", "VRM10"}
    assert runtime["includePlatforms"] == []


def test_editor_build_isolated_from_runtime_assembly() -> None:
    editor = json.loads(
        (ASSETS / "Editor" / "BodyRig.ReferenceRenderer.Editor.asmdef").read_text(encoding="utf-8")
    )

    assert editor["name"] == "BodyRig.ReferenceRenderer.Editor"
    assert editor["references"] == ["BodyRig.ReferenceRenderer.Runtime"]
    assert editor["includePlatforms"] == ["Editor"]
