from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path
from typing import Any

from bodyrig.package import validate_package
from bodyrig.skin_qa import SkinQaError, _accessor, _parse_glb

FORMAT = "bodyrig-mesh-topology-qa"
VERSION = 1


class MeshTopologyQaError(ValueError):
    pass


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


def _triangle_metrics(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ab = _distance(a, b)
    bc = _distance(b, c)
    ca = _distance(c, a)
    max_edge = max(ab, bc, ca)

    ux, uy, uz = (b[index] - a[index] for index in range(3))
    vx, vy, vz = (c[index] - a[index] for index in range(3))
    cross_x = uy * vz - uz * vy
    cross_y = uz * vx - ux * vz
    cross_z = ux * vy - uy * vx
    double_area = math.sqrt(cross_x * cross_x + cross_y * cross_y + cross_z * cross_z)
    altitude = double_area / max(max_edge, 1e-12)
    aspect = max_edge / max(altitude, 1e-12)
    return max_edge, altitude, aspect


def analyze_avatar(avatar: bytes, *, body_id: str, package_sha256: str) -> dict[str, Any]:
    try:
        document, binary = _parse_glb(avatar)
    except SkinQaError as exc:
        raise MeshTopologyQaError(str(exc)) from exc

    meshes = document.get("meshes")
    if not isinstance(meshes, list):
        raise MeshTopologyQaError("mesh topology QA: glTF meshes are missing")

    primitive: dict[str, Any] | None = None
    for mesh in meshes:
        if not isinstance(mesh, dict):
            continue
        candidates = mesh.get("primitives", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            attributes = candidate.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes or "indices" not in candidate:
                continue
            if primitive is not None:
                raise MeshTopologyQaError("mesh topology QA: multiple indexed POSITION primitives are unsupported")
            primitive = candidate
    if primitive is None:
        raise MeshTopologyQaError("mesh topology QA: no indexed POSITION primitive found")

    attributes = primitive["attributes"]
    positions_raw = _accessor(document, binary, int(attributes["POSITION"]), label="POSITION")
    indices_raw = _accessor(document, binary, int(primitive["indices"]), label="indices")
    if any(len(value) != 3 for value in positions_raw):
        raise MeshTopologyQaError("mesh topology QA: POSITION accessor must be VEC3")
    if any(len(value) != 1 for value in indices_raw):
        raise MeshTopologyQaError("mesh topology QA: index accessor must be SCALAR")

    positions = [tuple(float(component) for component in value) for value in positions_raw]
    if any(not all(math.isfinite(component) for component in point) for point in positions):
        raise MeshTopologyQaError("mesh topology QA: POSITION contains non-finite values")
    indices = [int(value[0]) for value in indices_raw]
    if len(indices) < 3 or len(indices) % 3:
        raise MeshTopologyQaError("mesh topology QA: triangle index count must be a non-empty multiple of three")
    if any(index < 0 or index >= len(positions) for index in indices):
        raise MeshTopologyQaError("mesh topology QA: triangle index is outside POSITION range")

    xs = [point[0] for point in positions]
    ys = [point[1] for point in positions]
    zs = [point[2] for point in positions]
    extent_x = max(xs) - min(xs)
    extent_y = max(ys) - min(ys)
    extent_z = max(zs) - min(zs)
    body_scale = math.sqrt(extent_x * extent_x + extent_y * extent_y + extent_z * extent_z)
    body_height = extent_y
    if not math.isfinite(body_scale) or body_scale <= 1e-6 or not math.isfinite(body_height) or body_height <= 1e-6:
        raise MeshTopologyQaError("mesh topology QA: body bounds are invalid")

    edge_ratios: list[float] = []
    aspects: list[float] = []
    long_edge_count = 0
    severe_edge_count = 0
    sliver_bridge_count = 0
    degenerate_count = 0
    worst: list[dict[str, Any]] = []

    for triangle_index in range(0, len(indices), 3):
        ia, ib, ic = indices[triangle_index : triangle_index + 3]
        max_edge, altitude, aspect = _triangle_metrics(positions[ia], positions[ib], positions[ic])
        edge_ratio = max_edge / body_scale
        edge_ratios.append(edge_ratio)
        aspects.append(aspect)
        if altitude <= body_scale * 1e-7:
            degenerate_count += 1
        if edge_ratio >= 0.08:
            long_edge_count += 1
        if edge_ratio >= 0.16:
            severe_edge_count += 1
        is_sliver_bridge = edge_ratio >= 0.04 and aspect >= 12.0
        if is_sliver_bridge:
            sliver_bridge_count += 1
        if edge_ratio >= 0.08 or is_sliver_bridge:
            worst.append(
                {
                    "triangle": triangle_index // 3,
                    "indices": [ia, ib, ic],
                    "max_edge": round(max_edge, 8),
                    "max_edge_body_scale_ratio": round(edge_ratio, 8),
                    "min_altitude": round(altitude, 8),
                    "aspect": round(aspect, 4),
                }
            )

    triangle_count = len(indices) // 3
    worst.sort(key=lambda item: (item["max_edge_body_scale_ratio"], item["aspect"]), reverse=True)
    return {
        "format": FORMAT,
        "version": VERSION,
        "semantics": "geometry-diagnostics-not-identity-verification",
        "body_id": body_id,
        "package_sha256": package_sha256,
        "mesh": {
            "vertex_count": len(positions),
            "triangle_count": triangle_count,
            "body_scale": round(body_scale, 8),
            "body_height": round(body_height, 8),
            "bounds": {
                "x": round(extent_x, 8),
                "y": round(extent_y, 8),
                "z": round(extent_z, 8),
            },
        },
        "triangle_geometry": {
            "max_edge_body_scale_ratio_p95": round(_quantile(edge_ratios, 0.95), 8),
            "max_edge_body_scale_ratio_p99": round(_quantile(edge_ratios, 0.99), 8),
            "max_edge_body_scale_ratio_max": round(max(edge_ratios), 8),
            "aspect_p95": round(_quantile(aspects, 0.95), 4),
            "aspect_p99": round(_quantile(aspects, 0.99), 4),
            "aspect_max": round(max(aspects), 4),
            "long_edge_count_ge_0_08_body_scale": long_edge_count,
            "severe_edge_count_ge_0_16_body_scale": severe_edge_count,
            "sliver_bridge_count_edge_ge_0_04_aspect_ge_12": sliver_bridge_count,
            "degenerate_triangle_count": degenerate_count,
            "candidate_ratio": round((long_edge_count + sliver_bridge_count) / max(1, triangle_count), 8),
        },
        "diagnostic_thresholds": {
            "long_edge_body_scale_ratio": 0.08,
            "severe_edge_body_scale_ratio": 0.16,
            "sliver_min_edge_body_scale_ratio": 0.04,
            "sliver_min_aspect": 12.0,
        },
        "worst_candidates": worst[:50],
    }


def analyze_package(path: str | Path) -> dict[str, Any]:
    package_path = Path(path).expanduser().resolve()
    validated = validate_package(package_path)
    body_id = validated.manifest.get("id")
    if not isinstance(body_id, str) or not body_id:
        raise MeshTopologyQaError("mesh topology QA: package body id is invalid")
    import hashlib

    digest = hashlib.sha256(package_path.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise MeshTopologyQaError("mesh topology QA: package avatar.vrm is unavailable") from exc
    return analyze_avatar(avatar, body_id=body_id, package_sha256=digest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure BodyRig VRM triangle topology without rendering or GPU work.")
    parser.add_argument("package", help="BodyRig .mrbody package")
    parser.add_argument("--out", default="", help="optional JSON output path")
    args = parser.parse_args(argv)
    try:
        result = analyze_package(args.package)
    except (OSError, MeshTopologyQaError, ValueError) as exc:
        print(f"BodyRig mesh topology QA: FAIL: {exc}")
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        output = Path(args.out).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(output)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
