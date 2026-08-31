from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs"


def test_canonical_fidelity_rig_uses_three_shaped_directional_lights() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert '"BodyRig Fidelity Key Light"' in source
    assert '"BodyRig Fidelity Fill Light"' in source
    assert '"BodyRig Fidelity Rim Light"' in source
    assert source.count("CreateDirectionalLight(") == 4  # helper declaration + three fixed calls
    assert "light.type = LightType.Directional;" in source


def test_canonical_fidelity_rig_reduces_flat_ambient_fill() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;" in source
    assert "RenderSettings.ambientLight = new Color(0.16f, 0.16f, 0.16f, 1f);" in source
    assert "new Color(0.45f, 0.45f, 0.45f, 1f)" not in source


def test_portrait_light_recipe_is_fixed_for_comparable_snapshots() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "1.15f" in source
    assert "new Vector3(36f, -32f, 0f)" in source
    assert "0.28f" in source
    assert "new Vector3(18f, 145f, 0f)" in source
    assert "0.38f" in source
    assert "new Vector3(52f, 205f, 0f)" in source
