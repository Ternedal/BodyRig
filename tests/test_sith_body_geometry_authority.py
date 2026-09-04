from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.sith_body_geometry_authority as authority


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    stage = workspace / "sith-input-v1"
    smplx = stage / "smplx"
    meshes = stage / "meshes"
    smplx.mkdir(parents=True)
    meshes.mkdir()

    donor = (b"v 0 0 0\n" * 20)
    fit = json.dumps({"fixture": True}).encode()
    mesh = (b"mtllib 000.mtl\n" + b"v 0 0 0\n" * 20)
    material = b"newmtl 000\nmap_Kd 000.png\n"
    texture = b"\x89PNG\r\n\x1a\nfixture"
    (smplx / "000_smplx.obj").write_bytes(donor)
    (smplx / "000_fit.json").write_bytes(fit)
    (meshes / "000_reco.obj").write_bytes(mesh)
    (meshes / "000.mtl").write_bytes(material)
    (meshes / "000.png").write_bytes(texture)

    reconstruction = {
        "format": "bodyrig-sith-reconstruction",
        "version": 1,
        "reconstruction": {
            "grid_size": 300,
            "save_uv": True,
            "smplx_obj_sha256": _sha(donor),
            "fit_params_sha256": _sha(fit),
            "mesh_obj_sha256": _sha(mesh),
            "mesh_mtl_sha256": _sha(material),
            "mesh_texture_name": "000.png",
            "mesh_texture_sha256": _sha(texture),
        },
    }
    (stage / "reconstruction.json").write_text(json.dumps(reconstruction), encoding="utf-8")
    return workspace


def _document() -> dict:
    return {
        "asset": {"version": "2.0"},
        "extras": {
            "bodyrig": {
                "geometryAuthority": {
                    "method": "smplx-fitted-donor-topology-v1",
                    "sourceMeshGeometryUsed": False,
                    "stableTopology": True,
                }
            }
        },
        "buffers": [{"byteLength": 0}],
    }


def test_bind_adds_exact_nonactivating_source_geometry_authority(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    document = _document()
    captured: dict = {}
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (document, b""))

    def fake_write(value, binary):
        captured.update(value)
        assert binary == b""
        return b"bound-vrm"

    monkeypatch.setattr(authority, "_write_glb", fake_write)
    monkeypatch.setattr(authority, "validate_vrm1", lambda _raw: None)

    result = authority.bind_sith_body_geometry_authority(b"input-vrm", workspace)
    assert result == b"bound-vrm"
    receipt = captured["extras"]["bodyrig"]["sourceGeometryAuthority"]
    assert receipt["format"] == authority.FORMAT
    assert receipt["method"] == "exact-sith-reconstruction-bytes-v1"
    assert receipt["exactByteBinding"] is True
    assert receipt["hairCandidateBindingEligible"] is True
    assert receipt["productionActivation"] is False
    assert receipt["fittedDonorObjSha256"] == _sha((workspace / "sith-input-v1/smplx/000_smplx.obj").read_bytes())
    assert receipt["sourceMeshSha256"] == _sha((workspace / "sith-input-v1/meshes/000_reco.obj").read_bytes())


def test_bind_fails_closed_when_reconstruction_artifact_changes(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "sith-input-v1/meshes/000_reco.obj").write_bytes(b"tampered")
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (_document(), b""))
    monkeypatch.setattr(authority, "validate_vrm1", lambda _raw: None)

    with pytest.raises(authority.SithBodyGeometryAuthorityError, match="byte hash mismatch: sourceMeshSha256"):
        authority.bind_sith_body_geometry_authority(b"input-vrm", workspace)


def test_bind_requires_canonical_donor_topology_authority(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    document = _document()
    document["extras"]["bodyrig"]["geometryAuthority"]["stableTopology"] = False
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (document, b""))

    with pytest.raises(authority.SithBodyGeometryAuthorityError, match="geometry authority is incompatible"):
        authority.bind_sith_body_geometry_authority(b"input-vrm", workspace)


def test_bind_is_create_only_at_metadata_boundary(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    document = _document()
    document["extras"]["bodyrig"]["sourceGeometryAuthority"] = {"old": True}
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (document, b""))

    with pytest.raises(authority.SithBodyGeometryAuthorityError, match="already bound"):
        authority.bind_sith_body_geometry_authority(b"input-vrm", workspace)


def test_builtin_external_fitter_binds_geometry_before_package_and_retention() -> None:
    text = (Path(__file__).resolve().parents[1] / "bodyrig" / "external_fitter_cli.py").read_text(encoding="utf-8")
    bind = text.index("avatar_vrm = bind_sith_body_geometry_authority(")
    package = text.index("build_package(")
    retained = text.index("publish_retained_anatomy_source(")
    assert bind < package < retained
    assert "avatar_vrm=avatar_vrm" in text
    assert "SithBodyGeometryAuthorityError" in text
