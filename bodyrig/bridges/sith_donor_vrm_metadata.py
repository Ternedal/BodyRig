from __future__ import annotations

from typing import Any, Mapping

from sith_pbr_material import PbrMaterialError, _read_glb, _write_glb


class DonorVrmMetadataError(ValueError):
    pass


def mark_donor_topology(
    avatar_vrm: bytes,
    *,
    mapping_metrics: Mapping[str, float | str],
) -> bytes:
    """Replace legacy transfer metadata with truthful donor-topology authority."""

    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise DonorVrmMetadataError(str(exc)) from exc

    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise DonorVrmMetadataError("BodyRig VRM metadata is missing")
    transfer = bodyrig.get("rigTransfer")
    if not isinstance(transfer, dict):
        raise DonorVrmMetadataError("BodyRig rigTransfer metadata is missing")
    if transfer.get("method") != "nearest-smplx-vertex-lbs-inverse":
        raise DonorVrmMetadataError("unexpected pre-donor rig transfer method")
    if "geometryAuthority" in bodyrig or "appearanceTransfer" in bodyrig:
        raise DonorVrmMetadataError("donor topology metadata is already present")

    source_p95 = mapping_metrics.get("source_surface_distance_p95")
    source_max = mapping_metrics.get("source_surface_distance_max")
    seam_ratio = mapping_metrics.get("multi_uv_source_vertex_ratio")
    for label, value in (
        ("source_surface_distance_p95", source_p95),
        ("source_surface_distance_max", source_max),
        ("multi_uv_source_vertex_ratio", seam_ratio),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0.0:
            raise DonorVrmMetadataError(f"{label} is invalid")

    transfer["method"] = "smplx-donor-topology-direct-lbs-v1"
    transfer["nearestDistanceP95"] = 0.0
    transfer["nearestDistanceMax"] = 0.0
    bodyrig["geometryAuthority"] = {
        "method": "smplx-fitted-donor-topology-v1",
        "sourceMeshGeometryUsed": False,
        "stableTopology": True,
    }
    bodyrig["appearanceTransfer"] = {
        "method": "sith-source-nearest-textured-vertex-uv-v1",
        "sourceSurfaceDistanceP95": round(float(source_p95), 6),
        "sourceSurfaceDistanceMax": round(float(source_max), 6),
        "multiUvSourceVertexRatio": round(float(seam_ratio), 6),
        "sourceTextureBytesPreserved": True,
        "geometryModified": False,
    }
    meshes = document.get("meshes")
    if not isinstance(meshes, list) or len(meshes) != 1 or not isinstance(meshes[0], dict):
        raise DonorVrmMetadataError("BodyRig donor VRM mesh contract is unsupported")
    meshes[0]["name"] = "BodyRigSmplxDonorTopologyMesh"
    return _write_glb(document, binary)
