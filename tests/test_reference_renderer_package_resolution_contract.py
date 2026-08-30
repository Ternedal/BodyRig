import json
from pathlib import Path


MANIFEST = Path("reference-renderer/Packages/manifest.json")
BUILD_SCRIPT = Path("reference-renderer/build-reference-renderer.ps1")


def test_unity6_registry_package_contract_matches_physical_resolution() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dependencies = manifest["dependencies"]

    assert dependencies["com.unity.test-framework"] == "1.6.0"
    assert dependencies["com.unity.mathematics"] == "1.2.6"
    assert dependencies["com.unity.timeline"] == "1.7.6"

    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '"com.unity.test-framework" = "1.6.0"' in script
    assert '"com.unity.mathematics" = "1.2.6"' in script
    assert '"com.unity.timeline" = "1.7.6"' in script
    assert "does not match the renderer package contract" in script
    assert "does not match the UniVRM dependency contract" not in script


def test_univrm_git_pins_remain_exact() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dependencies = manifest["dependencies"]
    revision = "a4711bbf8c4d10659d3e5568c2e3d7d595005e51"

    assert dependencies["com.vrmc.gltf"] == f"https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#{revision}"
    assert dependencies["com.vrmc.vrm"] == f"https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#{revision}"
