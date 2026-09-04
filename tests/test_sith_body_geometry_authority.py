from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.sith_body_geometry_authority as authority
from bodyrig.sith_reconstruction_authority import (
    AUTHORITY_FORMAT as RECONSTRUCTION_AUTHORITY_FORMAT,
    AUTHORITY_VERSION as RECONSTRUCTION_AUTHORITY_VERSION,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _workspace(tmp_path: Path, *, gender: str = "female") -> Path:
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
    reconstruction_path = stage / "reconstruction.json"
    reconstruction_path.write_text(json.dumps(reconstruction), encoding="utf-8")
    model_authority = {
        "format": RECONSTRUCTION_AUTHORITY_FORMAT,
        "version": RECONSTRUCTION_AUTHORITY_VERSION,
        "body_model_gender": gender,
        "smplx_fit_profile": authority.SMPLX_FIT_PROFILE,
        "reconstruction_sha256": _sha(reconstruction_path.read_bytes()),
    }
    (stage / authority.AUTHORITY_FILENAME).write_text(json.dumps(model_authority), encoding="utf-8")
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


def _adjustment() -> dict:
    return {
        "format": "bodyrig-bodyprint-adjustment",
        "version": 1,
        "feedback_sha256": "8" * 64,
        "changes": [
            {
                "field": "shape.shoulder_to_height",
                "delta": 0.004,
                "reason": "reviewed shoulder proportion",
            },
            {
                "field": "motion.energy",
                "delta": 0.02,
                "reason": "reviewed motion only",
            },
        ],
    }


def _patch_glb(monkeypatch, document: dict, captured: dict) -> None:
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (document, b""))

    def fake_write(value, binary):
        captured.update(value)
        assert binary == b""
        return b"bound-vrm"

    monkeypatch.setattr(authority, "_write_glb", fake_write)
    monkeypatch.setattr(authority, "validate_vrm1", lambda _raw: None)


def test_bind_adds_exact_nonactivating_source_geometry_authority(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, gender="female")
    document = _document()
    captured: dict = {}
    _patch_glb(monkeypatch, document, captured)

    result = authority.bind_sith_body_geometry_authority(b"input-vrm", workspace)
    assert result == b"bound-vrm"
    receipt = captured["extras"]["bodyrig"]["sourceGeometryAuthority"]
    assert receipt["format"] == authority.FORMAT
    assert receipt["version"] == authority.VERSION == 2
    assert receipt["method"] == "exact-sith-reconstruction-bytes-v2"
    assert receipt["bodyModelGender"] == "female"
    assert receipt["smplxFitProfile"] == authority.SMPLX_FIT_PROFILE
    assert receipt["reconstructionAuthoritySha256"] == _sha(
        (workspace / "sith-input-v1" / authority.AUTHORITY_FILENAME).read_bytes()
    )
    assert receipt["bodyprintGeometryAdjustment"] == {
        "method": authority.BODYPRINT_REPLAY_METHOD,
        "applied": False,
        "evidenceSha256": None,
        "changes": [],
    }
    assert receipt["exactByteBinding"] is True
    assert receipt["hairCandidateBindingEligible"] is True
    assert receipt["productionActivation"] is False
    assert receipt["fittedDonorObjSha256"] == _sha((workspace / "sith-input-v1/smplx/000_smplx.obj").read_bytes())
    assert receipt["sourceMeshSha256"] == _sha((workspace / "sith-input-v1/meshes/000_reco.obj").read_bytes())


def test_bind_embeds_only_replayable_geometry_deltas_and_exact_evidence_sha(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    captured: dict = {}
    _patch_glb(monkeypatch, _document(), captured)
    evidence_sha = "7" * 64

    authority.bind_sith_body_geometry_authority(
        b"input-vrm",
        workspace,
        bodyprint_adjustment=_adjustment(),
        bodyprint_adjustment_evidence_sha256=evidence_sha,
    )

    receipt = captured["extras"]["bodyrig"]["sourceGeometryAuthority"]
    replay = receipt["bodyprintGeometryAdjustment"]
    assert replay == {
        "method": authority.BODYPRINT_REPLAY_METHOD,
        "applied": True,
        "evidenceSha256": evidence_sha,
        "changes": [{"field": "shape.shoulder_to_height", "delta": 0.004}],
    }
    serialized = json.dumps(receipt, sort_keys=True)
    assert "reviewed shoulder proportion" not in serialized
    assert "reviewed motion only" not in serialized
    assert "feedback_sha256" not in serialized
    assert "motion.energy" not in serialized


def test_bind_rejects_adjustment_without_exact_evidence_sha(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (_document(), b""))

    with pytest.raises(authority.SithBodyGeometryAuthorityError, match="missing its exact evidence SHA"):
        authority.bind_sith_body_geometry_authority(
            b"input-vrm",
            workspace,
            bodyprint_adjustment=_adjustment(),
        )


def test_bind_fails_closed_when_reconstruction_artifact_changes(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "sith-input-v1/meshes/000_reco.obj").write_bytes(b"tampered")
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (_document(), b""))
    monkeypatch.setattr(authority, "validate_vrm1", lambda _raw: None)

    with pytest.raises(authority.SithBodyGeometryAuthorityError, match="byte hash mismatch: sourceMeshSha256"):
        authority.bind_sith_body_geometry_authority(b"input-vrm", workspace)


def test_bind_rejects_missing_or_wrong_model_family_authority(monkeypatch, tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    authority_path = workspace / "sith-input-v1" / authority.AUTHORITY_FILENAME
    authority_path.unlink()
    monkeypatch.setattr(authority, "_read_glb", lambda _raw: (_document(), b""))
    with pytest.raises(authority.SithBodyGeometryAuthorityError, match="model-family authority is missing"):
        authority.bind_sith_body_geometry_authority(b"input-vrm", workspace)

    workspace = _workspace(tmp_path / "second")
    authority_path = workspace / "sith-input-v1" / authority.AUTHORITY_FILENAME
    value = json.loads(authority_path.read_text(encoding="utf-8"))
    value["body_model_gender"] = "unknown"
    authority_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(authority.SithBodyGeometryAuthorityError, match="body-model gender is invalid"):
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
    package = text.index("build_package(", bind)
    retained = text.index("publish_retained_anatomy_source(", package)
    assert bind < package < retained
    assert "bodyprint_adjustment=adjustment_request" in text
    assert "bodyprint_adjustment_evidence_sha256=adjustment_hash" in text
    assert "avatar_vrm=avatar_vrm" in text
    assert "SithBodyGeometryAuthorityError" in text
