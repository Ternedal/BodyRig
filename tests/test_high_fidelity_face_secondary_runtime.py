from __future__ import annotations

import hashlib

import pytest

import bodyrig.high_fidelity_face_secondary_runtime as runtime
from bodyrig.bridges.face_secondary_fidelity import current_face_secondary_receipt
from bodyrig.bridges.sith_pbr_material import _read_glb, _write_glb


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _top(*, eyes: str = "complete") -> dict[str, object]:
    components = {
        "body_anatomy": "complete",
        "skin_appearance": "partial",
        "hair": "complete",
        "eyes": eyes,
        "face_secondary": "missing",
    }
    blockers = [name for name, status in components.items() if status != "complete"]
    return {
        "format": "bodyrig-avatar-fidelity-components",
        "version": 1,
        "components": components,
        "highFidelityReady": False,
        "blockers": blockers,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def _appearance() -> dict[str, object]:
    return {
        "method": "canonical-smplx-anatomy-normal-bake-v2",
        "canonicalDonorAtlas": True,
        "sourceDerivedPbrApplied": True,
        "boundedBaseColorRefinementApplied": True,
        "generativeAppearanceSynthesis": False,
        "geometryModified": False,
        "bakedBaseColorSha256": "1" * 64,
    }


def _source_vrm(*, eyes: str = "complete", rotate_head: bool = False) -> bytes:
    nodes = [
        {"name": "smplx_head", "translation": [0.0, 1.60, 0.0]},
        {"name": "smplx_jaw", "translation": [0.0, 1.51, 0.035]},
        {"name": "smplx_left_eye", "translation": [0.031, 1.64, 0.075]},
        {"name": "smplx_right_eye", "translation": [-0.031, 1.64, 0.075]},
        {"name": "ExistingBody", "mesh": 0, "skin": 0},
    ]
    if rotate_head:
        nodes[0]["rotation"] = [0.0, 0.0, 0.0, 1.0]
    binary = b"existing-body"
    document = {
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [],
        "accessors": [],
        "materials": [{"name": "ExistingBodyMaterial"}],
        "meshes": [{"name": "ExistingBodyMesh", "primitives": []}],
        "nodes": nodes,
        "skins": [{"joints": [0, 1, 2, 3]}],
        "scenes": [{"nodes": [0, 1, 2, 3, 4]}],
        "extras": {
            "bodyrig": {
                "fidelityComponents": _top(eyes=eyes),
                "faceSecondaryFidelity": current_face_secondary_receipt(),
                "appearanceTransfer": _appearance(),
                "eyePromotion": {
                    "format": "bodyrig-eye-promotion",
                    "version": 1,
                    "sourceHairRuntimeImported": False,
                    "productionActivation": False,
                },
                "keepMe": {"authority": "survives-face-secondary-runtime"},
            }
        },
    }
    return _write_glb(document, binary)


def test_build_runtime_adds_all_secondary_geometry_without_component_authority(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source_vrm()
    package = tmp_path / "source.mrbody"
    package.write_bytes(b"package-bytes")
    monkeypatch.setattr(runtime, "_package_avatar", lambda path: (source, "body-1", _sha(package.read_bytes())))

    output = tmp_path / "face-runtime"
    value = runtime.build_runtime(package, output, bodyrig_revision="a" * 40)
    reread = runtime.read_runtime(output)

    assert reread["reviewVrmSha256"] == value["reviewVrmSha256"]
    assert value["candidateComponents"] == {
        "eyebrow_appearance": "partial",
        "lip_boundary": "partial",
        "mouth_interior": "partial",
        "teeth": "partial",
        "eyelashes": "partial",
    }
    assert value["faceSecondaryComponentAuthority"] is False
    assert value["packageMutationPerformed"] is False
    assert value["productionActivation"] is False
    assert package.read_bytes() == b"package-bytes"

    document, _binary = _read_glb((output / runtime.REVIEW_VRM_NAME).read_bytes())
    names = [node.get("name") for node in document["nodes"] if isinstance(node, dict)]
    assert runtime.NODE_NAME in names
    material_names = {item.get("name") for item in document["materials"] if isinstance(item, dict)}
    assert set(runtime.MATERIAL_NAMES.values()).issubset(material_names)
    bodyrig = document["extras"]["bodyrig"]
    assert bodyrig["keepMe"] == {"authority": "survives-face-secondary-runtime"}
    assert bodyrig["fidelityComponents"]["components"]["face_secondary"] == "missing"
    assert bodyrig["faceSecondaryReviewRuntime"]["generativeIdentitySynthesis"] is False
    assert bodyrig["faceSecondaryReviewRuntime"]["faceSecondaryComponentAuthority"] is False
    metadata = bodyrig["faceSecondaryReviewRuntime"]
    assert metadata["mouthInteriorGeometry"] == "deterministic-rounded-oval-cavity-v2"
    assert metadata["teethGeometry"] == "deterministic-individual-rounded-dental-row-v2"
    assert metadata["eyelashGeometry"] == "deterministic-smplx-head-anchored-tapered-ribbon-v2"


def test_runtime_requires_promoted_eyes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source_vrm(eyes="partial")
    package = tmp_path / "source.mrbody"
    package.write_bytes(b"package")
    monkeypatch.setattr(runtime, "_package_avatar", lambda path: (source, "body-1", _sha(package.read_bytes())))

    with pytest.raises(runtime.HighFidelityFaceSecondaryRuntimeError, match="eyes=complete"):
        runtime.build_runtime(package, tmp_path / "out", bodyrig_revision="a" * 40)


def test_runtime_rejects_noncanonical_rotated_rest_joint(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source_vrm(rotate_head=True)
    package = tmp_path / "source.mrbody"
    package.write_bytes(b"package")
    monkeypatch.setattr(runtime, "_package_avatar", lambda path: (source, "body-1", _sha(package.read_bytes())))

    with pytest.raises(runtime.HighFidelityFaceSecondaryRuntimeError, match="translation-only"):
        runtime.build_runtime(package, tmp_path / "out", bodyrig_revision="a" * 40)


def test_runtime_is_create_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source_vrm()
    package = tmp_path / "source.mrbody"
    package.write_bytes(b"package")
    monkeypatch.setattr(runtime, "_package_avatar", lambda path: (source, "body-1", _sha(package.read_bytes())))
    output = tmp_path / "out"
    output.mkdir()

    with pytest.raises(runtime.HighFidelityFaceSecondaryRuntimeError, match="create-only"):
        runtime.build_runtime(package, output, bodyrig_revision="a" * 40)


def test_secondary_geometry_is_smooth_and_not_box_primitives() -> None:
    mouth = runtime._oval_prism(
        (0.0, 0.0, 0.0),
        (0.06, 0.015, 0.006),
        1,
    )
    upper = runtime._tooth_row(
        (0.0, 0.004, 0.003),
        (0.045, 0.006, 0.004),
        0,
        upper=True,
    )
    lower = runtime._tooth_row(
        (0.0, -0.004, 0.003),
        (0.043, 0.0055, 0.0038),
        1,
        upper=False,
    )
    lash = runtime._lash((0.03, 0.05, 0.02), 0.062, 0)

    mouth_positions, mouth_normals, mouth_faces, mouth_joint = mouth
    upper_positions, upper_normals, upper_faces, upper_joint = upper
    lower_positions, lower_normals, lower_faces, lower_joint = lower
    lash_positions, lash_normals, lash_faces, lash_joint = lash

    assert mouth_joint == 1
    assert len(mouth_positions) > 50
    assert len(mouth_positions) == len(mouth_normals)
    assert len(mouth_faces) > 50

    assert upper_joint == 0
    assert lower_joint == 1
    assert len(upper_positions) > 300
    assert len(lower_positions) > 300
    assert len(upper_positions) == len(upper_normals)
    assert len(lower_positions) == len(lower_normals)
    assert len(upper_faces) > 500
    assert len(lower_faces) > 500

    assert lash_joint == 0
    assert len(lash_positions) == 34
    assert len(lash_positions) == len(lash_normals)
    assert len(lash_faces) == 32


def test_tooth_row_has_visible_depth_curve() -> None:
    positions, _normals, _faces, _joint = runtime._tooth_row(
        (0.0, 0.0, 0.0),
        (0.05, 0.006, 0.004),
        0,
        upper=True,
    )
    z_values = [position[2] for position in positions]

    assert max(z_values) - min(z_values) > 0.003
