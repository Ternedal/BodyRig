from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import bodyrig.photoidentity_dental_reconstruction as subject
from bodyrig.bridges.sith_pbr_material import _write_glb


REVISION = "a" * 40
PERFORMER = "42"


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _private_entry(
    *,
    reference: str,
    scene: str,
    ordinal: int,
    source: Path,
    review: Path,
) -> dict:
    return {
        "reference": reference,
        "domain": subject.DOMAIN,
        "scene_id": scene,
        "region": "mouth_teeth",
        "source_ordinal": ordinal,
        "source_media_path": str(source),
        "source_media_sha256": _sha(source),
        "review_image_path": str(review),
        "review_image_sha256": _sha(review),
        "source_quality": 0.95,
    }


def _fixture_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, malicious_reference: bool = False):
    source_a = tmp_path / "source-a.mp4"
    source_b = tmp_path / "source-b.mp4"
    review_a = tmp_path / "review-a.png"
    review_b = tmp_path / "review-b.png"
    source_a.write_bytes(b"source-a")
    source_b.write_bytes(b"source-b")
    review_a.write_bytes(b"review-a")
    review_b.write_bytes(b"review-b")

    first_ref = "../escape" if malicious_reference else "oral-a"
    entries = [
        _private_entry(reference=first_ref, scene="scene-a", ordinal=1, source=source_a, review=review_a),
        _private_entry(reference="oral-b", scene="scene-b", ordinal=2, source=source_b, review=review_b),
    ]
    manifest = {
        "format": subject.PRIVATE_FORMAT,
        "version": subject.PRIVATE_VERSION,
        "performer_id": PERFORMER,
        "bodyrig_revision": REVISION,
        "anatomy_observation_evidence_sha256": "1" * 64,
        "anatomy_sufficiency_report_sha256": "2" * 64,
        "private_source_manifest_set_sha256": "3" * 64,
        "marker_inventory_path": str(tmp_path / "markers.json"),
        "marker_inventory_sha256": "4" * 64,
        "entries": entries,
    }
    private_manifest = tmp_path / "private-review.json"
    private_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text("{}", encoding="utf-8")
    selected = [
        {field: entry[field] for field in subject.PUBLIC_ENTRY_FIELDS}
        for entry in entries
    ]
    attestation = {
        "performer_id": PERFORMER,
        "bodyrig_revision": REVISION,
        "confirm_oral_teeth_photoidentity": True,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "selected_evidence": selected,
    }
    monkeypatch.setattr(subject, "read_attestation", lambda *_args, **_kwargs: dict(attestation))
    return private_manifest, attestation_path, entries


def _config() -> dict:
    return {
        "format": subject.CONFIG_FORMAT,
        "version": 1,
        "adapter": "fixture-dental",
        "revision": "fixture-v1",
        "command": [
            "python",
            "adapter.py",
            "--bodyrig-dental-input",
            "<input>",
            "--bodyrig-dental-output",
            "<output>",
        ],
        "capabilities": {
            "oral_teeth_geometry": True,
            "oral_teeth_appearance": True,
            "source_grounded": True,
            "generative_identity_synthesis": False,
        },
        "timeout_seconds": 60,
    }


def _dental_vrm(*, generic: bool = False, png_texture: bool = True) -> bytes:
    texture_bytes = b"\x89PNG\r\n\x1a\nfixture-dental-texture" if png_texture else b"not-a-png-texture"
    binary = bytearray(texture_bytes)
    views: list[dict] = []
    accessors: list[dict] = []

    def add_accessor(raw: bytes, *, component: int, count: int, kind: str, target: int) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        views.append({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(raw),
            "target": target,
        })
        accessors.append({
            "bufferView": len(views) - 1,
            "componentType": component,
            "count": count,
            "type": kind,
        })
        return len(accessors) - 1

    positions = [
        (-0.01, 0.00, 0.00),
        (0.01, 0.00, 0.00),
        (0.00, 0.01, 0.00),
    ]
    normals = [(0.0, 0.0, 1.0)] * 3
    uvs = [(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)]
    position_accessor = add_accessor(
        b"".join(struct.pack("<3f", *item) for item in positions),
        component=5126,
        count=3,
        kind="VEC3",
        target=34962,
    )
    normal_accessor = add_accessor(
        b"".join(struct.pack("<3f", *item) for item in normals),
        component=5126,
        count=3,
        kind="VEC3",
        target=34962,
    )
    uv_accessor = add_accessor(
        b"".join(struct.pack("<2f", *item) for item in uvs),
        component=5126,
        count=3,
        kind="VEC2",
        target=34962,
    )
    joints_accessor = add_accessor(
        b"".join(struct.pack("<4H", 0, 0, 0, 0) for _ in positions),
        component=5123,
        count=3,
        kind="VEC4",
        target=34962,
    )
    weights_accessor = add_accessor(
        b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in positions),
        component=5126,
        count=3,
        kind="VEC4",
        target=34962,
    )
    index_accessor = add_accessor(
        struct.pack("<3H", 0, 1, 2),
        component=5123,
        count=3,
        kind="SCALAR",
        target=34963,
    )
    attrs = {
        "POSITION": position_accessor,
        "NORMAL": normal_accessor,
        "TEXCOORD_0": uv_accessor,
        "JOINTS_0": joints_accessor,
        "WEIGHTS_0": weights_accessor,
    }
    primitives = [
        {
            "attributes": dict(attrs),
            "indices": index_accessor,
            "material": 0,
            "mode": 4,
            "extras": {"bodyrigDentalRole": "mouth_interior"},
        },
        {
            "attributes": dict(attrs),
            "indices": index_accessor,
            "material": 1,
            "mode": 4,
            "extras": {"bodyrigDentalRole": "upper_teeth"},
        },
        {
            "attributes": dict(attrs),
            "indices": index_accessor,
            "material": 1,
            "mode": 4,
            "extras": {"bodyrigDentalRole": "lower_teeth"},
        },
    ]
    metadata = {
        "adapter": "fixture-dental",
        "adapterRevision": "fixture-v1",
        "bodyrigRevision": REVISION,
        "performerId": PERFORMER,
        "inputManifestSha256": "7" * 64,
        "fineIdentityAttestationSha256": "8" * 64,
        "sourceDerivedDentalIdentity": not generic,
        "genericSecondaryAnatomy": generic,
        "generativeIdentitySynthesis": False,
        "humanReviewRequired": True,
        "promotionAuthority": False,
        "productionActivation": False,
    }
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(texture_bytes)},
            *views,
        ],
        "accessors": [
            {**item, "bufferView": int(item["bufferView"]) + 1}
            for item in accessors
        ],
        "images": [{"name": subject.DENTAL_IMAGE, "bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [
            {
                "name": subject.MOUTH_MATERIAL,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.2, 0.03, 0.04, 1.0],
                    "baseColorTexture": {"index": 0},
                },
            },
            {
                "name": subject.DENTAL_MATERIAL,
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            },
        ],
        "meshes": [{"name": subject.MESH_NAME, "primitives": primitives}],
        "nodes": [{"name": subject.NODE_NAME, "mesh": 0, "skin": 0}],
        "skins": [{"joints": [0]}],
        "scenes": [{"nodes": [0]}],
        "extras": {"bodyrig": {"dentalSourceRuntime": metadata}},
    }
    return _write_glb(document, bytes(binary))


def test_adapter_config_requires_source_grounded_non_generative_capabilities() -> None:
    assert subject.validate_adapter_config(_config())["adapter"] == "fixture-dental"
    bad = _config()
    bad["capabilities"] = dict(bad["capabilities"])
    bad["capabilities"]["generative_identity_synthesis"] = True
    with pytest.raises(subject.PhotoIdentityDentalReconstructionError, match="without generative"):
        subject.validate_adapter_config(bad)


def test_private_oral_sources_must_match_exact_public_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_manifest, attestation_path, entries = _fixture_evidence(tmp_path, monkeypatch)
    _manifest, _attestation, oral = subject.load_oral_source_evidence(
        private_manifest_path=private_manifest,
        attestation_path=attestation_path,
        bodyrig_revision=REVISION,
    )
    assert [item["reference"] for item in oral] == ["oral-a", "oral-b"]

    broken = json.loads(private_manifest.read_text(encoding="utf-8"))
    broken["entries"][0]["review_image_sha256"] = "f" * 64
    private_manifest.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(subject.PhotoIdentityDentalReconstructionError, match="private/public oral/teeth evidence mismatch"):
        subject.load_oral_source_evidence(
            private_manifest_path=private_manifest,
            attestation_path=attestation_path,
            bodyrig_revision=REVISION,
        )


def test_prepare_workspace_uses_hash_safe_staged_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_manifest, attestation_path, _entries = _fixture_evidence(
        tmp_path,
        monkeypatch,
        malicious_reference=True,
    )
    output = tmp_path / "dental-workspace"
    result = subject.prepare_input_workspace(
        private_manifest_path=private_manifest,
        attestation_path=attestation_path,
        output_dir=output,
        bodyrig_revision=REVISION,
    )
    staged = [Path(item["staged_review_image"]) for item in result["evidence"]]
    assert all(path.parent == output / "input" for path in staged)
    assert all("escape" not in path.name for path in staged)
    assert all(path.is_file() for path in staged)
    assert result["distinct_scene_count"] == 2
    assert result["generic_guessing_permitted"] is False


def test_dental_vrm_requires_source_derived_non_generic_payload() -> None:
    detail = subject.validate_dental_vrm(_dental_vrm())
    assert detail["metadata"]["sourceDerivedDentalIdentity"] is True
    assert len(detail["texture_sha256"]) == 64
    with pytest.raises(subject.PhotoIdentityDentalReconstructionError, match="authority boundary"):
        subject.validate_dental_vrm(_dental_vrm(generic=True))
    with pytest.raises(subject.PhotoIdentityDentalReconstructionError, match="texture bytes are not PNG"):
        subject.validate_dental_vrm(_dental_vrm(png_texture=False))


def test_adapter_result_is_bound_to_exact_input_attestation_and_vrm(tmp_path: Path) -> None:
    input_manifest = tmp_path / "input.json"
    input_manifest.write_text('{"input":"exact"}\n', encoding="utf-8")
    attestation = tmp_path / "attestation.json"
    attestation.write_text('{"attested":"exact"}\n', encoding="utf-8")
    vrm_path = tmp_path / "dental-source.vrm"
    vrm_bytes = _dental_vrm()
    vrm_path.write_bytes(vrm_bytes)

    # Rebuild the fixture metadata with the exact runtime hashes expected by validation.
    from bodyrig.bridges.sith_pbr_material import _read_glb
    document, binary = _read_glb(vrm_bytes)
    metadata = document["extras"]["bodyrig"]["dentalSourceRuntime"]
    metadata["inputManifestSha256"] = _sha(input_manifest)
    metadata["fineIdentityAttestationSha256"] = _sha(attestation)
    vrm_bytes = _write_glb(document, binary)
    vrm_path.write_bytes(vrm_bytes)

    result = {
        "format": subject.RESULT_FORMAT,
        "version": 1,
        "adapter": "fixture-dental",
        "adapter_revision": "fixture-v1",
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "input_manifest_sha256": _sha(input_manifest),
        "fine_identity_attestation_sha256": _sha(attestation),
        "dental_vrm_sha256": _sha(vrm_path),
        "source_references": ["oral-a", "oral-b"],
        "source_derived_dental_identity": True,
        "generic_secondary_anatomy": False,
        "generative_identity_synthesis": False,
        "mouth_interior_source_derived": True,
        "upper_teeth_source_derived": True,
        "lower_teeth_source_derived": True,
        "appearance_source_derived": True,
        "human_review_required": True,
        "promotion_authority": False,
        "production_activation": False,
    }
    result_path = tmp_path / "dental-reconstruction.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    validated = subject.validate_adapter_result(
        result_path=result_path,
        vrm_path=vrm_path,
        input_manifest_path=input_manifest,
        config=_config(),
        performer_id=PERFORMER,
        bodyrig_revision=REVISION,
        attestation_sha256=_sha(attestation),
        source_references=["oral-a", "oral-b"],
    )
    assert validated["source_derived_dental_identity"] is True

    result["generic_secondary_anatomy"] = True
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(subject.PhotoIdentityDentalReconstructionError, match="generic_secondary_anatomy"):
        subject.validate_adapter_result(
            result_path=result_path,
            vrm_path=vrm_path,
            input_manifest_path=input_manifest,
            config=_config(),
            performer_id=PERFORMER,
            bodyrig_revision=REVISION,
            attestation_sha256=_sha(attestation),
            source_references=["oral-a", "oral-b"],
        )



def _materialize_reconstruction_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    private_manifest, attestation_path, _entries = _fixture_evidence(tmp_path, monkeypatch)
    root = tmp_path / "persisted-dental"
    prepared = subject.prepare_input_workspace(
        private_manifest_path=private_manifest,
        attestation_path=attestation_path,
        output_dir=root,
        bodyrig_revision=REVISION,
    )
    input_manifest = Path(prepared["input_manifest_path"])
    attestation_sha = prepared["fine_identity_attestation_sha256"]
    output = root / "adapter-output"
    vrm_path = output / "dental-source.vrm"

    vrm = _dental_vrm()
    from bodyrig.bridges.sith_pbr_material import _read_glb
    document, binary = _read_glb(vrm)
    metadata = document["extras"]["bodyrig"]["dentalSourceRuntime"]
    metadata["inputManifestSha256"] = _sha(input_manifest)
    metadata["fineIdentityAttestationSha256"] = attestation_sha
    vrm = _write_glb(document, binary)
    vrm_path.write_bytes(vrm)

    result = {
        "format": subject.RESULT_FORMAT,
        "version": 1,
        "adapter": "fixture-dental",
        "adapter_revision": "fixture-v1",
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "input_manifest_sha256": _sha(input_manifest),
        "fine_identity_attestation_sha256": attestation_sha,
        "dental_vrm_sha256": _sha(vrm_path),
        "source_references": [item["reference"] for item in prepared["evidence"]],
        "source_derived_dental_identity": True,
        "generic_secondary_anatomy": False,
        "generative_identity_synthesis": False,
        "mouth_interior_source_derived": True,
        "upper_teeth_source_derived": True,
        "lower_teeth_source_derived": True,
        "appearance_source_derived": True,
        "human_review_required": True,
        "promotion_authority": False,
        "production_activation": False,
    }
    (output / "dental-reconstruction.json").write_text(
        json.dumps(result),
        encoding="utf-8",
    )
    return root


def test_reconstruction_workspace_readback_revalidates_private_staged_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _materialize_reconstruction_workspace(tmp_path, monkeypatch)
    value = subject.read_reconstruction_workspace(root)
    assert value["source_derived_dental_identity"] is True
    assert value["generic_secondary_anatomy"] is False
    assert len(value["dental_texture_sha256"]) == 64

    manifest = json.loads((root / "dental-reconstruction-input.json").read_text(encoding="utf-8"))
    staged = Path(manifest["evidence"][0]["staged_review_image"])
    staged.write_bytes(staged.read_bytes() + b"tamper")
    with pytest.raises(subject.PhotoIdentityDentalReconstructionError, match="staged dental review image bytes changed"):
        subject.read_reconstruction_workspace(root)


def test_reconstruction_workspace_readback_rejects_result_or_vrm_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _materialize_reconstruction_workspace(tmp_path, monkeypatch)
    result_path = root / "adapter-output" / "dental-reconstruction.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["source_references"] = list(reversed(result["source_references"]))
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(subject.PhotoIdentityDentalReconstructionError, match="source_references"):
        subject.read_reconstruction_workspace(root)
