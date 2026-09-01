from __future__ import annotations

import math
from typing import Any, Mapping

from sith_pbr_material import PbrMaterialError, _read_glb, _write_glb


class DonorVrmMetadataError(ValueError):
    pass


def _finite_nonnegative_metric(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DonorVrmMetadataError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise DonorVrmMetadataError(f"{label} is invalid")
    return result


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise DonorVrmMetadataError(f"{label} is invalid")
    digest = value.lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise DonorVrmMetadataError(f"{label} is invalid")
    return digest


def _appearance_refinement_authority(bodyrig: Mapping[str, Any]) -> dict[str, Any]:
    material = bodyrig.get("materialRefinement")
    if not isinstance(material, dict):
        raise DonorVrmMetadataError("source-derived PBR refinement receipt is missing")
    pbr_method = material.get("method")
    if not isinstance(pbr_method, str) or not pbr_method.strip():
        raise DonorVrmMetadataError("source-derived PBR refinement method is invalid")
    if material.get("physicalMeasurement") is not False or material.get("sourceDerivedHeuristic") is not True:
        raise DonorVrmMetadataError("source-derived PBR refinement authority is invalid")

    detail = bodyrig.get("baseColorDetailRefinement")
    if not isinstance(detail, dict):
        raise DonorVrmMetadataError("bounded base-color refinement receipt is missing")
    detail_method = detail.get("method")
    if not isinstance(detail_method, str) or not detail_method.strip():
        raise DonorVrmMetadataError("bounded base-color refinement method is invalid")
    if detail.get("sourceDerived") is not True or detail.get("generative") is not False:
        raise DonorVrmMetadataError("bounded base-color refinement authority is invalid")
    source_sha = _sha256(detail.get("sourceBaseColorSha256"), label="source base-color SHA-256")
    refined_sha = _sha256(detail.get("refinedBaseColorSha256"), label="refined base-color SHA-256")
    max_delta = _finite_nonnegative_metric(
        detail.get("maxObservedChannelDelta"),
        label="base-color max observed channel delta",
    )
    cap = _finite_nonnegative_metric(detail.get("channelDeltaCap"), label="base-color channel delta cap")
    if max_delta > cap + (1.0 / 255.0) + 1e-6:
        raise DonorVrmMetadataError("bounded base-color refinement exceeded its declared cap")

    return {
        "pbr_method": pbr_method.strip(),
        "basecolor_method": detail_method.strip(),
        "source_basecolor_sha256": source_sha,
        "refined_basecolor_sha256": refined_sha,
        "max_observed_channel_delta": max_delta,
        "channel_delta_cap": cap,
    }


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

    appearance = _appearance_refinement_authority(bodyrig)
    source_p95 = _finite_nonnegative_metric(
        mapping_metrics.get("source_surface_distance_p95"),
        label="source_surface_distance_p95",
    )
    source_max = _finite_nonnegative_metric(
        mapping_metrics.get("source_surface_distance_max"),
        label="source_surface_distance_max",
    )
    seam_ratio = _finite_nonnegative_metric(
        mapping_metrics.get("multi_uv_source_vertex_ratio"),
        label="multi_uv_source_vertex_ratio",
    )
    if seam_ratio > 1.0:
        raise DonorVrmMetadataError("multi_uv_source_vertex_ratio is invalid")

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
        "sourceSurfaceDistanceP95": round(source_p95, 6),
        "sourceSurfaceDistanceMax": round(source_max, 6),
        "multiUvSourceVertexRatio": round(seam_ratio, 6),
        "sourceTextureBytesPreserved": True,
        "activeBaseColorUsesExactSourceBytes": False,
        "sourceDerivedPbrApplied": True,
        "boundedBaseColorRefinementApplied": True,
        "pbrRefinementMethod": appearance["pbr_method"],
        "baseColorRefinementMethod": appearance["basecolor_method"],
        "sourceBaseColorSha256": appearance["source_basecolor_sha256"],
        "activeBaseColorSha256": appearance["refined_basecolor_sha256"],
        "baseColorMaxObservedChannelDelta": round(float(appearance["max_observed_channel_delta"]), 6),
        "baseColorChannelDeltaCap": round(float(appearance["channel_delta_cap"]), 6),
        "geometryModified": False,
    }
    meshes = document.get("meshes")
    if not isinstance(meshes, list) or len(meshes) != 1 or not isinstance(meshes[0], dict):
        raise DonorVrmMetadataError("BodyRig donor VRM mesh contract is unsupported")
    meshes[0]["name"] = "BodyRigSmplxDonorTopologyMesh"
    return _write_glb(document, binary)
