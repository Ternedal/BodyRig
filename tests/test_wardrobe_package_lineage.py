from pathlib import Path
from types import SimpleNamespace

import bodyrig.wardrobe_package_lineage as lineage


SHA = {
    "reconstructionSha256": "1" * 64,
    "reconstructionAuthoritySha256": "2" * 64,
    "fittedDonorObjSha256": "3" * 64,
    "fitParamsSha256": "4" * 64,
    "sourceMeshSha256": "5" * 64,
    "sourceMaterialSha256": "6" * 64,
    "sourceTextureSha256": "7" * 64,
}


class _Archive:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, name: str) -> bytes:
        assert name == "avatar.vrm"
        return b"avatar-vrm"


def _geometry() -> dict:
    return {
        "format": "bodyrig-sith-body-geometry-authority",
        "version": 2,
        "method": "exact-sith-reconstruction-bytes-v2",
        **SHA,
        "bodyModelGender": "neutral",
        "smplxFitProfile": "smplx-neutral-v1",
        "sourceTextureName": "source.png",
        "bodyprintGeometryAdjustment": {"method": "bodyrig-bodyprint-shape-adjust-v1", "applied": False, "evidenceSha256": None, "changes": []},
        "exactByteBinding": True,
        "hairCandidateBindingEligible": True,
        "productionActivation": False,
    }


def test_package_lineage_exposes_exact_source_outer_surface(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "person.mrbody"
    package.write_bytes(b"package")
    monkeypatch.setattr(lineage, "validate_package", lambda _path: SimpleNamespace(manifest={"id": "body-0123456789abcdef0123456789abcdef"}))
    monkeypatch.setattr(lineage.zipfile, "ZipFile", _Archive)
    monkeypatch.setattr(lineage, "read_sith_body_geometry_authority", lambda _avatar: _geometry())

    value = lineage.inspect_wardrobe_package_lineage(package)

    assert value["format"] == "bodyrig-wardrobe-package-lineage"
    assert value["canonical_body_id"] == "body-0123456789abcdef0123456789abcdef"
    assert value["source_mesh_sha256"] == "5" * 64
    assert value["source_material_sha256"] == "6" * 64
    assert value["source_texture_sha256"] == "7" * 64
    assert value["source_outer_surface_used"] is True
    assert value["source_grounded"] is True
    assert value["comparison_only"] is True
    assert value["human_review_required"] is True
    assert value["production_activation"] is False


def test_package_lineage_rejects_non_exact_source_geometry(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "person.mrbody"
    package.write_bytes(b"package")
    bad = _geometry()
    bad["exactByteBinding"] = False
    monkeypatch.setattr(lineage, "validate_package", lambda _path: SimpleNamespace(manifest={"id": "body-0123456789abcdef0123456789abcdef"}))
    monkeypatch.setattr(lineage.zipfile, "ZipFile", _Archive)
    monkeypatch.setattr(lineage, "read_sith_body_geometry_authority", lambda _avatar: bad)

    try:
        lineage.inspect_wardrobe_package_lineage(package)
    except lineage.WardrobePackageLineageError as exc:
        assert "exact byte binding" in str(exc)
    else:
        raise AssertionError("non-exact source geometry unexpectedly became wardrobe lineage")
