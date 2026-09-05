#!/usr/bin/env python
"""Build a comparison-only eye runtime on the exact BodyRig base avatar.

The bridge intentionally excludes source-hair runtime content. It reuses the exact
combined-runtime eye input validation, SMPL-X eye geometry construction and
primitive generation, then serializes only the source-derived eye surface and
corneal shell. A higher-level gate must compare the semantic runtime fingerprint
against the human-reviewed combined hair+eye runtime before this output can be
used for any promotion decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import sith_hair_eye_review_runtime as combined
import sith_hair_review_runtime as hair
from sith_pbr_material import PbrMaterialError, _read_glb, _write_glb

FORMAT = "bodyrig-source-eye-review-bridge"
VERSION = 1


class EyeReviewRuntimeError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clean_base(document: Mapping[str, Any]) -> None:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise EyeReviewRuntimeError("base avatar lacks BodyRig metadata")
    if "hairReviewRuntime" in bodyrig or "eyeReviewRuntime" in bodyrig:
        raise EyeReviewRuntimeError("eye-only rebuild base already carries review runtime overlays")
    nodes = document.get("nodes")
    materials = document.get("materials")
    if not isinstance(nodes, list) or not isinstance(materials, list):
        raise EyeReviewRuntimeError("base avatar glTF node/material arrays are missing")
    forbidden_nodes = {"BodyRigSourceHairReview", "BodyRigSourceEyeReview"}
    forbidden_materials = {"BodyRigSourceEyeSurface", "BodyRigCorneaReview"}
    if any(isinstance(item, dict) and item.get("name") in forbidden_nodes for item in nodes):
        raise EyeReviewRuntimeError("eye-only rebuild base already contains review runtime nodes")
    if any(isinstance(item, dict) and item.get("name") in forbidden_materials for item in materials):
        raise EyeReviewRuntimeError("eye-only rebuild base already contains review eye materials")


def _append_eyes_to_clean_base(
    *,
    document: dict[str, Any],
    binary_bytes: bytes,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    source_bake_png: bytes,
    metadata: Mapping[str, Any],
) -> tuple[bytes, int, dict[str, int]]:
    try:
        import numpy as np
    except ImportError as exc:
        raise EyeReviewRuntimeError(f"numpy is required for eye GLB serialization: {exc}") from exc

    _clean_base(document)
    keys = ("bufferViews", "accessors", "images", "textures", "materials", "meshes", "nodes", "scenes", "samplers", "buffers")
    arrays = {key: document.get(key) for key in keys}
    if any(not isinstance(value, list) for value in arrays.values()):
        raise EyeReviewRuntimeError("base avatar glTF arrays are incomplete")
    views = arrays["bufferViews"]
    accessors = arrays["accessors"]
    images = arrays["images"]
    textures = arrays["textures"]
    materials = arrays["materials"]
    meshes = arrays["meshes"]
    nodes = arrays["nodes"]
    scenes = arrays["scenes"]
    samplers = arrays["samplers"]
    buffers = arrays["buffers"]
    assert isinstance(views, list) and isinstance(accessors, list) and isinstance(images, list)
    assert isinstance(textures, list) and isinstance(materials, list) and isinstance(meshes, list)
    assert isinstance(nodes, list) and isinstance(scenes, list) and isinstance(samplers, list) and isinstance(buffers, list)
    if not samplers or len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise EyeReviewRuntimeError("base avatar sampler/buffer contract is unsupported")
    if not scenes or not isinstance(scenes[0], dict) or not isinstance(scenes[0].get("nodes"), list):
        raise EyeReviewRuntimeError("base avatar scene contract is unsupported")
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise EyeReviewRuntimeError("base avatar BodyRig metadata disappeared")

    binary = bytearray(binary_bytes)

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        view: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    def add_accessor(array: Any, *, component: int, kind: str, target: int | None = None, bounds: bool = False) -> int:
        if component == 5126:
            raw = array.astype("<f4", copy=False).tobytes()
        elif component == 5123:
            raw = array.astype("<u2", copy=False).tobytes()
        elif component == 5125:
            raw = array.astype("<u4", copy=False).tobytes()
        else:
            raise EyeReviewRuntimeError("unsupported eye accessor component type")
        view = add_view(raw, target=target)
        accessor: dict[str, Any] = {"bufferView": view, "componentType": component, "count": len(array), "type": kind}
        if bounds:
            accessor["min"] = [float(value) for value in array.min(axis=0)]
            accessor["max"] = [float(value) for value in array.max(axis=0)]
        accessors.append(accessor)
        return len(accessors) - 1

    texture_view = add_view(source_bake_png)
    images.append({"name": "BodyRigSourceEyeBake", "bufferView": texture_view, "mimeType": "image/png"})
    textures.append({"sampler": 0, "source": len(images) - 1})
    eye_texture = len(textures) - 1
    materials.append(
        {
            "name": "BodyRigSourceEyeSurface",
            "doubleSided": False,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": eye_texture},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.36,
            },
        }
    )
    surface_material = len(materials) - 1
    materials.append(
        {
            "name": "BodyRigCorneaReview",
            "doubleSided": False,
            "alphaMode": "BLEND",
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 0.11],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.04,
            },
        }
    )
    cornea_material = len(materials) - 1

    primitives: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for side_name, side in (("left", left), ("right", right)):
        surface = combined._primitive_arrays(np, side=side, scale=combined.SURFACE_SCALE)
        cornea = combined._primitive_arrays(np, side=side, scale=combined.CORNEA_SCALE)
        for label, arrays_for_primitive, material in (
            ("surface", surface, surface_material),
            ("cornea", cornea, cornea_material),
        ):
            pos, normals, uv, joints, weights, indices = arrays_for_primitive
            pos_accessor = add_accessor(pos, component=5126, kind="VEC3", target=34962, bounds=True)
            normal_accessor = add_accessor(normals, component=5126, kind="VEC3", target=34962)
            uv_accessor = add_accessor(uv, component=5126, kind="VEC2", target=34962)
            joints_accessor = add_accessor(joints, component=5123, kind="VEC4", target=34962)
            weights_accessor = add_accessor(weights, component=5126, kind="VEC4", target=34962)
            index_accessor = add_accessor(indices, component=5125, kind="SCALAR", target=34963)
            primitives.append(
                {
                    "attributes": {
                        "POSITION": pos_accessor,
                        "NORMAL": normal_accessor,
                        "TEXCOORD_0": uv_accessor,
                        "JOINTS_0": joints_accessor,
                        "WEIGHTS_0": weights_accessor,
                    },
                    "indices": index_accessor,
                    "material": material,
                    "mode": 4,
                }
            )
            counts[f"{side_name}_{label}_vertices"] = int(len(pos))
            counts[f"{side_name}_{label}_faces"] = int(indices.size // 3)

    meshes.append({"name": "BodyRigSourceEyeReviewMesh", "primitives": primitives})
    mesh_index = len(meshes) - 1
    nodes.append({"name": "BodyRigSourceEyeReview", "mesh": mesh_index, "skin": 0})
    scenes[0]["nodes"].append(len(nodes) - 1)
    bodyrig["eyeReviewRuntime"] = dict(metadata)
    buffers[0]["byteLength"] = len(binary)
    return _write_glb(document, bytes(binary)), mesh_index, counts


def build(
    *,
    avatar_vrm: Path,
    candidate_workspace: Path,
    eye_geometry_dir: Path,
    eye_appearance_dir: Path,
    model_dir: str,
    smplx_uv_obj: Path,
    output_vrm: Path,
    output_result: Path,
) -> dict[str, Any]:
    avatar_vrm = avatar_vrm.expanduser().resolve()
    candidate_workspace = candidate_workspace.expanduser().resolve()
    eye_geometry_dir = eye_geometry_dir.expanduser().resolve()
    eye_appearance_dir = eye_appearance_dir.expanduser().resolve()
    smplx_uv_obj = smplx_uv_obj.expanduser().resolve()
    output_vrm = output_vrm.expanduser().resolve()
    output_result = output_result.expanduser().resolve()
    if output_vrm.exists() or output_result.exists():
        raise EyeReviewRuntimeError("eye-only review output is create-only")
    for path, label in (
        (avatar_vrm, "base avatar"),
        (smplx_uv_obj, "SMPL-X UV authority"),
    ):
        if not path.is_file():
            raise EyeReviewRuntimeError(f"{label} is missing: {path}")
    if not candidate_workspace.is_dir() or not eye_geometry_dir.is_dir() or not eye_appearance_dir.is_dir():
        raise EyeReviewRuntimeError("eye-only runtime input directories are missing")
    output_vrm.parent.mkdir(parents=True, exist_ok=True)

    avatar_bytes = avatar_vrm.read_bytes()
    try:
        document, binary = _read_glb(avatar_bytes)
    except PbrMaterialError as exc:
        raise EyeReviewRuntimeError(f"base avatar is invalid GLB: {exc}") from exc
    _clean_base(document)
    try:
        geometry = hair._geometry(document)
        component, appearance, bake_bytes = combined._validate_eye_inputs(
            geometry=geometry,
            eye_geometry_dir=eye_geometry_dir,
            eye_appearance_dir=eye_appearance_dir,
        )
        left, right, final_joints, parents = combined._eye_geometry_runtime(
            candidate_workspace=candidate_workspace,
            model_dir=model_dir,
            uv_obj=smplx_uv_obj,
            geometry=geometry,
            component=component,
        )
        hair._verify_avatar_skeleton(document, final_joints=final_joints, parents=parents)
    except Exception as exc:
        if isinstance(exc, EyeReviewRuntimeError):
            raise
        raise EyeReviewRuntimeError(f"eye-only source/runtime authority failed: {exc}") from exc

    eye_metadata = {
        "format": combined.EYE_METADATA_FORMAT,
        "version": combined.EYE_METADATA_VERSION,
        "eyeComponentReceiptSha256": _sha256(eye_geometry_dir / "eye-component-candidate.json"),
        "eyeAppearanceReceiptSha256": _sha256(eye_appearance_dir / "eye-appearance-candidate.json"),
        "canonicalEyeBakeSha256": appearance["canonicalBakeSha256"],
        "targetModelFamily": geometry["bodyModelGender"],
        "leftEyeJointIndex": combined.eye_geometry.LEFT_EYE_JOINT,
        "rightEyeJointIndex": combined.eye_geometry.RIGHT_EYE_JOINT,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "skinIndex": 0,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }
    eye_only, eye_mesh_index, counts = _append_eyes_to_clean_base(
        document=document,
        binary_bytes=binary,
        left=left,
        right=right,
        source_bake_png=bake_bytes,
        metadata=eye_metadata,
    )
    output_vrm.write_bytes(eye_only)
    result = {
        "format": FORMAT,
        "version": VERSION,
        "baseAvatarVrmSha256": _sha256_bytes(avatar_bytes),
        "eyeComponentReceiptSha256": eye_metadata["eyeComponentReceiptSha256"],
        "eyeAppearanceReceiptSha256": eye_metadata["eyeAppearanceReceiptSha256"],
        "canonicalEyeBakeSha256": eye_metadata["canonicalEyeBakeSha256"],
        "eyeMeshIndex": eye_mesh_index,
        "reviewVrmSha256": _sha256_bytes(eye_only),
        "targetModelFamily": geometry["bodyModelGender"],
        "leftEyeFaceCount": int(component["leftEyeFaceCount"]),
        "rightEyeFaceCount": int(component["rightEyeFaceCount"]),
        "leftEyeRuntimeVertices": counts["left_surface_vertices"],
        "rightEyeRuntimeVertices": counts["right_surface_vertices"],
        "sourceHairRuntimeApplied": False,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }
    output_result.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an eye-only review VRM from exact BodyRig source authority.")
    parser.add_argument("--avatar-vrm", required=True)
    parser.add_argument("--candidate-workspace", required=True)
    parser.add_argument("--eye-geometry-dir", required=True)
    parser.add_argument("--eye-appearance-dir", required=True)
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--smplx-uv-obj", required=True)
    parser.add_argument("--output-vrm", required=True)
    parser.add_argument("--output-result", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(
            avatar_vrm=Path(args.avatar_vrm),
            candidate_workspace=Path(args.candidate_workspace),
            eye_geometry_dir=Path(args.eye_geometry_dir),
            eye_appearance_dir=Path(args.eye_appearance_dir),
            model_dir=str(args.smplx_model_dir),
            smplx_uv_obj=Path(args.smplx_uv_obj),
            output_vrm=Path(args.output_vrm),
            output_result=Path(args.output_result),
        )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True, allow_nan=False))
        return 0
    except Exception as exc:
        print(f"BodyRig eye-only review runtime: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
