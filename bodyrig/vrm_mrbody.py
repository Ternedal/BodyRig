"""VRM → ``.mrbody`` adapter for converted third-party assets (#1401, renderer decision).

Kaliv has one runtime body ingress: ``.mrbody`` through
``BodyRigRemoteAvatarSource``. A converted third-party model enters through the
same door instead of a second Unity load path (ChatGPT's #1402 review, agreed by
Anders 2026-11-09). It uses ``.mrbody`` v1 as it is; there is no contract change:

- ``avatar.vrm`` is the exported VRM, validated by ``avatar.validate_vrm1``;
- ``bodyprint.json`` holds only ``shape``, **measured from the model** (bounds
  height, shoulder and hip spans, arm and leg lengths from the humanoid bones);
  no motion, expression or runtime observations are invented;
- ``provenance.json`` is ``synthetic_avatar: true`` with one
  ``third_party_conversion`` stage (and ``weight_transfer`` when it was applied);
  no file names or reference hashes;
- ``thumbnail.png`` is BodyRig's neutral placeholder silhouette.

**Identity boundary (#817).** The id is ``asset-<24 hex of the asset hash>``,
never ``bodyid-*``. ModelRig's Person Profile binds only ``bodyid-*`` bodies, so a
converted model can be shown, but it cannot be bound to a person or stand in for the
owner's twin. ``to_mrbody`` refuses to build anything else.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from bodyrig import package
from bodyrig.avatar import _thumbnail_png, parse_glb_json, validate_vrm1

ID_PREFIX = "asset-"
REFERENCE_HEIGHT_M = 1.70  # bodyprint height_scale is relative to 1.70 m (avatar.ProceduralAvatarFitter)
# BodyRig's hip_to_height is the pelvis width; the hip joints sit at +-0.33 of it
# (avatar.ProceduralAvatarFitter), so the measured joint span is divided by 0.66.
HIP_JOINT_SPAN_OF_WIDTH = 0.66
ADAPTER = "bodyrig.vrm_mrbody"
_ID_RE = re.compile(r"^asset-[0-9a-f]{24}$")


class VrmMrbodyError(ValueError):
    pass


# --- glTF node geometry ----------------------------------------------------------------------

def _quat_matrix(q: Sequence[float]) -> list[list[float]]:
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
            [0.0, 0.0, 0.0, 1.0]]


def _mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _local(node: Mapping[str, Any]) -> list[list[float]]:
    if "matrix" in node:
        m = node["matrix"]  # column-major
        return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
    t = node.get("translation", [0.0, 0.0, 0.0])
    s = node.get("scale", [1.0, 1.0, 1.0])
    r = _quat_matrix(node.get("rotation", [0.0, 0.0, 0.0, 1.0]))
    scale = [[s[0], 0, 0, 0], [0, s[1], 0, 0], [0, 0, s[2], 0], [0, 0, 0, 1]]
    trans = [[1, 0, 0, t[0]], [0, 1, 0, t[1]], [0, 0, 1, t[2]], [0, 0, 0, 1]]
    return _mul(trans, _mul(r, scale))


def node_world_matrices(doc: Mapping[str, Any]) -> list[list[list[float]]]:
    nodes = doc["nodes"]
    parent = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            parent[child] = index
    cache: dict[int, list[list[float]]] = {}

    def world(index: int, depth: int = 0) -> list[list[float]]:
        if depth > len(nodes):
            raise VrmMrbodyError("cycle in glTF node hierarchy")
        if index not in cache:
            local = _local(nodes[index])
            cache[index] = _mul(world(parent[index], depth + 1), local) if index in parent else local
        return cache[index]

    return [world(i) for i in range(len(nodes))]


def node_world_positions(doc: Mapping[str, Any]) -> list[tuple[float, float, float]]:
    return [tuple(m[r][3] for r in range(3)) for m in node_world_matrices(doc)]


def _bounds_height(doc: Mapping[str, Any]) -> float:
    """Height on the glTF up axis (Y) of every mesh's bounds, in world space.

    POSITION accessors carry min/max in mesh space. A skinned mesh is placed by its
    joints, so glTF ignores its node transform: its bounds are used as they are (bind
    space; Blender's exporter writes it in world units). A plain mesh node's bounds are
    transformed by the node's world matrix, which matters when meshes are scaled by
    their nodes (BodyRig's procedural avatar does this).
    """
    worlds = node_world_matrices(doc)
    lows, highs = [], []
    for node_index, node in enumerate(doc["nodes"]):
        if "mesh" not in node:
            continue
        matrix = None if "skin" in node else worlds[node_index]
        for primitive in doc["meshes"][node["mesh"]].get("primitives", []):
            index = primitive.get("attributes", {}).get("POSITION")
            if index is None:
                continue
            accessor = doc["accessors"][index]
            if "min" not in accessor or "max" not in accessor:
                continue
            lo, hi = accessor["min"], accessor["max"]
            for corner in ((x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])):
                if matrix is None:
                    y_world = corner[1]
                else:
                    y_world = sum(matrix[1][k] * corner[k] for k in range(3)) + matrix[1][3]
                lows.append(y_world)
                highs.append(y_world)
    if not lows:
        raise VrmMrbodyError("the VRM has no POSITION bounds to measure")
    return max(highs) - min(lows)


def measure_shape(vrm: bytes) -> dict[str, float]:
    """bodyprint ``shape`` measured from the model itself, in BodyRig's definitions.

    Shoulder width is the span between the upper-arm joints; hip width is the pelvis
    width (joint span / 0.66); arm and leg length are the summed bone lengths from the
    upper joint to the hand / foot; height is the world-space mesh bounds.
    """
    doc = parse_glb_json(vrm)
    bones = doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    positions = node_world_positions(doc)

    def at(bone: str) -> tuple[float, float, float]:
        entry = bones.get(bone)
        if not isinstance(entry, dict) or "node" not in entry:
            raise VrmMrbodyError(f"humanoid bone {bone} is missing")
        return positions[entry["node"]]

    height = _bounds_height(doc)
    if not 0.2 <= height <= 4.0 * REFERENCE_HEIGHT_M:
        raise VrmMrbodyError(f"implausible model height {height:.3f} m")

    def span(a: str, b: str) -> float:
        return math.dist(at(a), at(b))

    shape = {
        "height_scale": height / REFERENCE_HEIGHT_M,
        "shoulder_to_height": span("leftUpperArm", "rightUpperArm") / height,
        "hip_to_height": span("leftUpperLeg", "rightUpperLeg") / HIP_JOINT_SPAN_OF_WIDTH / height,
        "arm_to_height": (span("leftUpperArm", "leftLowerArm") + span("leftLowerArm", "leftHand")) / height,
        "leg_to_height": (span("leftUpperLeg", "leftLowerLeg") + span("leftLowerLeg", "leftFoot")) / height,
    }
    for key, value in shape.items():
        if not math.isfinite(value) or not 0.0 < value <= (4.0 if key == "height_scale" else 1.0):
            raise VrmMrbodyError(f"measured {key}={value!r} is outside the bodyprint range")
    return {key: round(value, 4) for key, value in shape.items()}


# --- package --------------------------------------------------------------------------------

def body_id_for(asset_sha256: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", asset_sha256 or ""):
        raise VrmMrbodyError("asset hash must be 64 lowercase hex")
    return ID_PREFIX + asset_sha256[:24]


def to_mrbody(vrm_path: Path, destination: Path, *, name: str, asset_sha256: str, created_at: str,
              export_revision: str, weight_transfer_applied: bool = False) -> dict[str, Any]:
    """Build and validate ``destination`` (.mrbody). Returns a small report."""
    body_id = body_id_for(asset_sha256)
    if not _ID_RE.fullmatch(body_id) or body_id.startswith("bodyid-"):
        raise VrmMrbodyError("a converted third-party asset must never get a bodyid-* identity")
    vrm = Path(vrm_path).read_bytes()
    validate_vrm1(vrm)
    shape = measure_shape(vrm)
    pipeline = [{"stage": "third_party_conversion", "adapter": "bodyrig.vrm_export", "revision": export_revision},
                {"stage": "mrbody_packaging", "adapter": ADAPTER, "revision": "v1"}]
    if weight_transfer_applied:
        pipeline.insert(1, {"stage": "weight_transfer", "adapter": "bodyrig.blender_vrm_weights", "revision": "v1"})
    provenance = {"format": "modelrig-body-provenance", "version": 1, "created_at": created_at,
                  "source": {"kind": "user-supplied-local-media", "count": 1}, "synthetic_avatar": True,
                  "pipeline": pipeline}
    bodyprint = {"format": "modelrig-bodyprint", "version": 1, "shape": shape}
    path = package.build_package(destination, body_id=body_id, name=name[:160], avatar_vrm=vrm,
                                 bodyprint=bodyprint, provenance=provenance, thumbnail_png=_thumbnail_png())
    validated = package.validate_package(path)  # build_package validates too; this is the boundary check
    return {"path": path.name, "id": body_id, "shape": shape, "bytes": path.stat().st_size,
            "identity": "none: third-party asset, cannot be bound to a Person (requires bodyid-*)",
            "validated": validated is not None}


def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


__all__ = ["VrmMrbodyError", "body_id_for", "measure_shape", "node_world_positions", "to_mrbody"]
