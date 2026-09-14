from __future__ import annotations

from pathlib import Path

PRODUCT = Path("bodyrig/bridges/sith_hair_review_runtime.py")
TEST = Path("tests/test_source_hair_binding_bridge_v1.py")

text = PRODUCT.read_text(encoding="utf-8")
anchor = "class HairReviewRuntimeError(ValueError):\n    pass\n\n\n"
helper = "class HairReviewRuntimeError(ValueError):\n    pass\n\n\ndef _numeric_version(value: Any, expected: int) -> bool:\n    return not isinstance(value, bool) and isinstance(value, (int, float)) and value == expected\n\n\n"
if text.count(anchor) != 1:
    raise SystemExit("HairReviewRuntimeError anchor mismatch")
text = text.replace(anchor, helper, 1)
old = '    if set(value) != required or value.get("format") != BINDING_FORMAT or value.get("version") != BINDING_VERSION:\n'
new = '    if (\n        set(value) != required\n        or value.get("format") != BINDING_FORMAT\n        or not _numeric_version(value.get("version"), BINDING_VERSION)\n    ):\n'
if text.count(old) != 1:
    raise SystemExit("binding version discriminator mismatch")
text = text.replace(old, new, 1)
PRODUCT.write_text(text, encoding="utf-8", newline="\n")

TEST.write_text(r'''from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

AVATAR_SHA = "a" * 64
PACKAGE_SHA = "b" * 64
CANDIDATE_SHA = "c" * 64
OBJ_SHA = "d" * 64
MTL_SHA = "e" * 64
TEXTURE_SHA = "f" * 64
GEOMETRY = {"fixture": "source-geometry"}


def _bridge(monkeypatch: pytest.MonkeyPatch):
    base = types.ModuleType("sith_smplx_vrm_fitter")
    monkeypatch.setitem(sys.modules, "sith_smplx_vrm_fitter", base)

    adjustment = types.ModuleType("bodyprint_shape_adjust")
    adjustment.ADJUSTMENT_FORMAT = "fixture-adjustment"
    adjustment.ADJUSTMENT_VERSION = 1
    adjustment.BodyprintAdjustmentError = RuntimeError
    adjustment.apply_shape_adjustment = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "bodyprint_shape_adjust", adjustment)

    pbr = types.ModuleType("sith_pbr_material")
    pbr.PbrMaterialError = RuntimeError
    pbr._read_glb = lambda _raw: ({}, b"")
    pbr._write_glb = lambda _document, _binary: b""
    monkeypatch.setitem(sys.modules, "sith_pbr_material", pbr)

    path = Path("bodyrig/bridges/sith_hair_review_runtime.py").resolve()
    spec = importlib.util.spec_from_file_location("bodyrig_test_sith_hair_review_runtime", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-source-hair-body-binding",
        "version": version,
        "bodyId": "body-fixture",
        "packageSha256": PACKAGE_SHA,
        "avatarVrmSha256": AVATAR_SHA,
        "sourceGeometryAuthority": GEOMETRY,
        "hairCandidateReceiptSha256": CANDIDATE_SHA,
        "hairObjSha256": OBJ_SHA,
        "hairMaterialSha256": MTL_SHA,
        "hairTextureSha256": TEXTURE_SHA,
        "bindingStatus": "exact-source-and-donor-match",
        "runtimeIntegrationRequired": True,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }


def _write(path: Path, version: object) -> None:
    path.write_text(json.dumps(_receipt(version)) + "\n", encoding="utf-8")


@pytest.mark.parametrize("bad_version", [True, False, "1", None, [], {}, 0, 2])
def test_binding_rejects_non_numeric_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_version: object,
) -> None:
    bridge = _bridge(monkeypatch)
    path = tmp_path / "source-hair-body-binding.json"
    _write(path, bad_version)
    with pytest.raises(bridge.HairReviewRuntimeError, match="fields do not match v1"):
        bridge._binding(path, avatar_sha=AVATAR_SHA, geometry=GEOMETRY)


@pytest.mark.parametrize("version", [1, 1.0])
def test_binding_preserves_numeric_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: object,
) -> None:
    bridge = _bridge(monkeypatch)
    path = tmp_path / "source-hair-body-binding.json"
    _write(path, version)
    result = bridge._binding(path, avatar_sha=AVATAR_SHA, geometry=GEOMETRY)
    assert result["version"] == version
    assert result["comparisonOnly"] is True
    assert result["humanReviewRequired"] is True
    assert result["productionActivation"] is False
'''.rstrip() + "\n", encoding="utf-8", newline="\n")
