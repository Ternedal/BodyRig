from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    _bodyrig,
    _indexed,
    _named_index,
    _primitive_materials,
    _read_glb_document,
    _require_scene_mesh,
    audit_high_fidelity_package,
)

FORMAT = "bodyrig-fidelity-component-completeness"
VERSION = 1

REQUIRED_CORE_COMPONENTS = (
    "body_anatomy",
    "skin_appearance",
    "hair",
    "eyes",
    "face_secondary",
)
REQUIRED_RENDER_PAYLOADS = (
    "hair",
    "eyes",
    "face_secondary",
    "hands_feet_nails",
)

FINGERNAIL_FIELD = "handsFeetNailsFingernailGeometry"
FINGERNAIL_FORMAT = "bodyrig-hands-feet-nails-fingernail-geometry"
FINGERNAIL_POLICY = "bodyrig-hands-feet-nails-fingernail-geometry-candidate-v1"
FINGERNAIL_NODE = "BodyRigFingernailPlates"
FINGERNAIL_MESH = "BodyRigFingernailPlateMesh"
FINGERNAIL_MATERIAL = "BodyRigFingernailPlateMaterial"

TOENAIL_FIELD = "handsFeetNailsToenailGeometry"
TOENAIL_FORMAT = "bodyrig-hands-feet-nails-toenail-geometry"
TOENAIL_POLICY = "bodyrig-hands-feet-nails-toenail-geometry-candidate-v1"
TOENAIL_NODE = "BodyRigToenailPlates"
TOENAIL_MESH = "BodyRigToenailPlateMesh"
TOENAIL_MATERIAL = "BodyRigToenailPlateMaterial"
TOENAIL_LANDMARK_AUTHORITY = "source-big-small-heel-deterministic-five-toe-interpolation-v1"


class FidelityComponentGateError(ValueError):
    pass


def _is_positive_int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _avatar_document(package: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(package, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise FidelityComponentGateError("could not read validated avatar.vrm") from exc
    try:
        return _read_glb_document(avatar)
    except HighFidelityPackageAuditError as exc:
        raise FidelityComponentGateError(str(exc)) from exc


def _audit_nail_geometry(
    document: Mapping[str, Any],
    bodyrig: Mapping[str, Any],
    *,
    label: str,
    metadata_field: str,
    expected_format: str,
    expected_policy: str,
    node_name: str,
    mesh_name: str,
    material_name: str,
    require_toe_authority: bool = False,
) -> dict[str, Any]:
    embedded = bodyrig.get(metadata_field)
    if not isinstance(embedded, Mapping):
        raise FidelityComponentGateError(f"{label} geometry authority is missing")
    if (
        embedded.get("format") != expected_format
        or isinstance(embedded.get("version"), bool)
        or embedded.get("version") != 1
        or embedded.get("policyRevision") != expected_policy
        or embedded.get("nodeName") != node_name
        or embedded.get("meshName") != mesh_name
        or embedded.get("materialName") != material_name
        or embedded.get("skinIndex") != 0
        or embedded.get("plateCount") != 10
        or embedded.get("sourceGrounded") is not True
        or embedded.get("additiveGeometryOnly") is not True
        or embedded.get("geometryModified") is not True
        or embedded.get("textureModified") is not False
        or embedded.get("humanReviewRequired") is not True
        or embedded.get("productionActivation") is not False
    ):
        raise FidelityComponentGateError(f"{label} geometry authority is invalid")

    if not _is_positive_int(embedded.get("triangleCount")) or not _is_positive_int(embedded.get("vertexCount")):
        raise FidelityComponentGateError(f"{label} geometry counts are invalid")
    per_plate = embedded.get("plateTriangleCounts")
    if (
        not isinstance(per_plate, Mapping)
        or len(per_plate) != 10
        or any(not isinstance(key, str) or not key or not _is_positive_int(value) for key, value in per_plate.items())
    ):
        raise FidelityComponentGateError(f"{label} per-plate geometry counts are invalid")

    if require_toe_authority:
        if (
            embedded.get("toeLandmarkAuthority") != TOENAIL_LANDMARK_AUTHORITY
            or embedded.get("individualMiddleToeLandmarksObserved") is not False
        ):
            raise FidelityComponentGateError("toenail source-landmark authority is invalid")

    node_index, mesh_index, mesh = _require_scene_mesh(
        document,
        component=label,
        node_name=node_name,
        mesh_name=mesh_name,
    )
    material_index = _named_index(document, "materials", material_name, label=f"{label} render payload")
    if material_index not in _primitive_materials(mesh, component=label):
        raise FidelityComponentGateError(f"{label} material is not used by canonical nail mesh")
    material = _indexed(document, "materials", material_index, label=f"{label} render material")
    pbr = material.get("pbrMetallicRoughness")
    if not isinstance(pbr, Mapping) or pbr.get("baseColorTexture") != {"index": 0}:
        raise FidelityComponentGateError(f"{label} material is not bound to canonical active base color")

    return {
        "node": node_index,
        "mesh": mesh_index,
        "material": material_index,
        "plate_count": 10,
        "triangle_count": int(embedded["triangleCount"]),
        "vertex_count": int(embedded["vertexCount"]),
        "source_grounded": True,
    }


def assess_package(path: str | Path) -> dict[str, Any]:
    package = Path(path).expanduser().resolve()
    if not package.is_file():
        raise FidelityComponentGateError(f"candidate package is missing: {package}")
    try:
        audit = audit_high_fidelity_package(package)
    except HighFidelityPackageAuditError as exc:
        raise FidelityComponentGateError(str(exc)) from exc

    components = audit.get("components")
    if not isinstance(components, Mapping):
        raise FidelityComponentGateError("high-fidelity component audit returned no component map")
    blockers = [name for name in REQUIRED_CORE_COMPONENTS if components.get(name) != "complete"]
    if blockers or audit.get("high_fidelity_ready") is not True:
        raise FidelityComponentGateError(
            "candidate is not core high-fidelity ready: " + ", ".join(blockers or ["readiness-authority"])
        )

    render_payloads = audit.get("render_payloads")
    if not isinstance(render_payloads, Mapping):
        raise FidelityComponentGateError("high-fidelity component audit returned no render payload map")
    missing_payloads = [name for name in REQUIRED_RENDER_PAYLOADS if name not in render_payloads]
    if missing_payloads:
        raise FidelityComponentGateError(
            "candidate lacks required concrete render payloads: " + ", ".join(missing_payloads)
        )
    if audit.get("human_review_required") is not True or audit.get("production_ready") is not False:
        raise FidelityComponentGateError("candidate crossed the human-review/production authority boundary")

    document = _avatar_document(package)
    bodyrig = _bodyrig(document)
    fingernails = _audit_nail_geometry(
        document,
        bodyrig,
        label="fingernails",
        metadata_field=FINGERNAIL_FIELD,
        expected_format=FINGERNAIL_FORMAT,
        expected_policy=FINGERNAIL_POLICY,
        node_name=FINGERNAIL_NODE,
        mesh_name=FINGERNAIL_MESH,
        material_name=FINGERNAIL_MATERIAL,
    )
    toenails = _audit_nail_geometry(
        document,
        bodyrig,
        label="toenails",
        metadata_field=TOENAIL_FIELD,
        expected_format=TOENAIL_FORMAT,
        expected_policy=TOENAIL_POLICY,
        node_name=TOENAIL_NODE,
        mesh_name=TOENAIL_MESH,
        material_name=TOENAIL_MATERIAL,
        require_toe_authority=True,
    )

    return {
        "format": FORMAT,
        "version": VERSION,
        "package_sha256": audit["package_sha256"],
        "canonical_body_id": audit["canonical_body_id"],
        "core_components": {name: "complete" for name in REQUIRED_CORE_COMPONENTS},
        "required_render_payloads": list(REQUIRED_RENDER_PAYLOADS),
        "fingernails": fingernails,
        "toenails": toenails,
        "full_fidelity_components_present": True,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": "component-completeness-not-visual-quality-acceptance",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless a BodyRig package carries concrete full-fidelity render components."
    )
    parser.add_argument("package")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    try:
        result = assess_package(args.package)
        encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.out:
            output = Path(args.out).expanduser().resolve()
            if output.exists():
                raise FidelityComponentGateError(f"component gate output already exists: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded, encoding="utf-8", newline="\n")
        else:
            print(encoded, end="")
    except (OSError, FidelityComponentGateError) as exc:
        print(f"BodyRig fidelity component gate: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
