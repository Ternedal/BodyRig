from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from bodyrig.avatar import AvatarError, validate_vrm1
from bodyrig.mesh_topology_qa import (
    LONG_EDGE_BODY_SCALE_RATIO,
    SLIVER_MIN_ASPECT,
    SLIVER_MIN_EDGE_BODY_SCALE_RATIO,
    _triangle_metrics,
    analyze_package,
)
from bodyrig.package import MRBodyError, build_package, validate_package
from bodyrig.skin_qa import SkinQaError, _accessor, _parse_glb

REPAIR_ADAPTER = "bodyrig.mesh_topology_repair"
REPAIR_REVISION = "1"
MAX_REMOVAL_RATIO = 0.01
DEGENERATE_ALTITUDE_BODY_SCALE_RATIO = 1e-7
_INDEX_COMPONENTS = {5121: ("B", 1, 0xFF), 5123: ("H", 2, 0xFFFF), 5125: ("I", 4, 0xFFFFFFFF)}


class MeshTopologyRepairError(ValueError):
    pass


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_primitive(document: dict[str, Any]) -> dict[str, Any]:
    meshes = document.get("meshes")
    if not isinstance(meshes, list):
        raise MeshTopologyRepairError("mesh topology repair: glTF meshes are missing")
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
                raise MeshTopologyRepairError("mesh topology repair: multiple indexed POSITION primitives are unsupported")
            primitive = candidate
    if primitive is None:
        raise MeshTopologyRepairError("mesh topology repair: no indexed POSITION primitive found")
    return primitive


def _is_repair_candidate(*, max_edge: float, altitude: float, aspect: float, body_scale: float) -> bool:
    if altitude <= body_scale * DEGENERATE_ALTITUDE_BODY_SCALE_RATIO:
        return True
    edge_ratio = max_edge / body_scale
    return edge_ratio >= LONG_EDGE_BODY_SCALE_RATIO or (
        edge_ratio >= SLIVER_MIN_EDGE_BODY_SCALE_RATIO and aspect >= SLIVER_MIN_ASPECT
    )


def _encode_indices(component_type: int, indices: list[int]) -> bytes:
    component = _INDEX_COMPONENTS.get(component_type)
    if component is None:
        raise MeshTopologyRepairError("mesh topology repair: index component type must be unsigned byte/short/int")
    fmt, _, maximum = component
    if not indices or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > maximum for value in indices):
        raise MeshTopologyRepairError("mesh topology repair: repaired indices exceed accessor component range")
    pack = struct.Struct("<" + fmt).pack
    return b"".join(pack(value) for value in indices)


def _replace_index_accessor(
    document: dict[str, Any],
    binary: bytes,
    *,
    accessor_index: int,
    new_indices: list[int],
) -> bytes:
    accessors = document.get("accessors")
    views = document.get("bufferViews")
    buffers = document.get("buffers")
    if not isinstance(accessors, list) or not isinstance(views, list) or not isinstance(buffers, list) or len(buffers) != 1:
        raise MeshTopologyRepairError("mesh topology repair: glTF accessor/buffer structure is unsupported")
    if not 0 <= accessor_index < len(accessors):
        raise MeshTopologyRepairError("mesh topology repair: index accessor is invalid")
    accessor = accessors[accessor_index]
    if not isinstance(accessor, dict) or accessor.get("type") != "SCALAR" or "sparse" in accessor:
        raise MeshTopologyRepairError("mesh topology repair: index accessor must be non-sparse SCALAR")
    view_index = accessor.get("bufferView")
    component_type = accessor.get("componentType")
    component = _INDEX_COMPONENTS.get(component_type)
    if isinstance(view_index, bool) or not isinstance(view_index, int) or not 0 <= view_index < len(views) or component is None:
        raise MeshTopologyRepairError("mesh topology repair: index accessor layout is unsupported")
    if int(accessor.get("byteOffset", 0)) != 0:
        raise MeshTopologyRepairError("mesh topology repair: non-zero index accessor byteOffset is unsupported")

    view = views[view_index]
    if not isinstance(view, dict) or view.get("buffer", 0) != 0 or "byteStride" in view:
        raise MeshTopologyRepairError("mesh topology repair: index bufferView layout is unsupported")
    for index, other in enumerate(accessors):
        if index != accessor_index and isinstance(other, dict) and other.get("bufferView") == view_index:
            raise MeshTopologyRepairError("mesh topology repair: index bufferView is shared with another accessor")

    _, component_size, _ = component
    old_count = accessor.get("count")
    if isinstance(old_count, bool) or not isinstance(old_count, int) or old_count <= 0:
        raise MeshTopologyRepairError("mesh topology repair: index accessor count is invalid")
    old_payload_length = old_count * component_size
    view_length = view.get("byteLength")
    old_start = int(view.get("byteOffset", 0))
    if isinstance(view_length, bool) or not isinstance(view_length, int) or view_length < old_payload_length:
        raise MeshTopologyRepairError("mesh topology repair: index bufferView is shorter than its accessor")
    if old_start < 0 or old_start + view_length > len(binary):
        raise MeshTopologyRepairError("mesh topology repair: index bufferView exceeds BIN chunk")

    following_offsets = [
        int(other.get("byteOffset", 0))
        for index, other in enumerate(views)
        if index != view_index
        and isinstance(other, dict)
        and other.get("buffer", 0) == 0
        and int(other.get("byteOffset", 0)) > old_start
    ]
    old_region_end = min(following_offsets) if following_offsets else len(binary)
    if old_start + view_length > old_region_end:
        raise MeshTopologyRepairError("mesh topology repair: index bufferView overlaps a following bufferView")

    encoded = _encode_indices(int(component_type), new_indices)
    replacement = encoded + b"\x00" * ((-len(encoded)) % 4)
    old_span = old_region_end - old_start
    new_binary = binary[:old_start] + replacement + binary[old_region_end:]
    delta = len(replacement) - old_span

    view["byteLength"] = len(encoded)
    accessor["count"] = len(new_indices)
    if "min" in accessor:
        accessor["min"] = [min(new_indices)]
    if "max" in accessor:
        accessor["max"] = [max(new_indices)]
    for index, other in enumerate(views):
        if index == view_index or not isinstance(other, dict) or other.get("buffer", 0) != 0:
            continue
        offset = int(other.get("byteOffset", 0))
        if offset >= old_region_end:
            other["byteOffset"] = offset + delta
    buffers[0]["byteLength"] = len(new_binary)
    return new_binary


def _encode_glb(document: dict[str, Any], binary: bytes) -> bytes:
    json_payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    json_payload += b" " * ((-len(json_payload)) % 4)
    binary_payload = binary + b"\x00" * ((-len(binary)) % 4)
    total = 12 + 8 + len(json_payload) + 8 + len(binary_payload)
    return b"".join(
        [
            b"glTF",
            (2).to_bytes(4, "little"),
            total.to_bytes(4, "little"),
            len(json_payload).to_bytes(4, "little"),
            b"JSON",
            json_payload,
            len(binary_payload).to_bytes(4, "little"),
            b"BIN\x00",
            binary_payload,
        ]
    )


def repair_avatar(avatar: bytes) -> tuple[bytes, dict[str, Any]]:
    try:
        document, raw_binary = _parse_glb(avatar)
    except SkinQaError as exc:
        raise MeshTopologyRepairError(str(exc)) from exc
    buffers = document.get("buffers")
    if not isinstance(buffers, list) or len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise MeshTopologyRepairError("mesh topology repair: expected one embedded glTF buffer")
    declared_length = buffers[0].get("byteLength")
    if isinstance(declared_length, bool) or not isinstance(declared_length, int) or not 0 < declared_length <= len(raw_binary):
        raise MeshTopologyRepairError("mesh topology repair: embedded buffer byteLength is invalid")
    binary = raw_binary[:declared_length]

    primitive = _find_primitive(document)
    attributes = primitive["attributes"]
    position_accessor = int(attributes["POSITION"])
    index_accessor = int(primitive["indices"])
    positions_raw = _accessor(document, binary, position_accessor, label="POSITION")
    indices_raw = _accessor(document, binary, index_accessor, label="indices")
    if any(len(row) != 3 for row in positions_raw) or any(len(row) != 1 for row in indices_raw):
        raise MeshTopologyRepairError("mesh topology repair: POSITION/indices accessor dimensions are invalid")
    positions = [tuple(float(value) for value in row) for row in positions_raw]
    if any(not all(math.isfinite(value) for value in point) for point in positions):
        raise MeshTopologyRepairError("mesh topology repair: POSITION contains non-finite values")
    indices = [int(row[0]) for row in indices_raw]
    if len(indices) < 3 or len(indices) % 3:
        raise MeshTopologyRepairError("mesh topology repair: index count must be a non-empty multiple of three")
    if any(index < 0 or index >= len(positions) for index in indices):
        raise MeshTopologyRepairError("mesh topology repair: index is outside POSITION range")

    xs = [point[0] for point in positions]
    ys = [point[1] for point in positions]
    zs = [point[2] for point in positions]
    body_scale = math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2)
    if not math.isfinite(body_scale) or body_scale <= 1e-6:
        raise MeshTopologyRepairError("mesh topology repair: body scale is invalid")

    repaired_indices: list[int] = []
    removed = 0
    removed_long = 0
    removed_sliver = 0
    removed_degenerate = 0
    for offset in range(0, len(indices), 3):
        ia, ib, ic = indices[offset : offset + 3]
        max_edge, altitude, aspect = _triangle_metrics(positions[ia], positions[ib], positions[ic])
        edge_ratio = max_edge / body_scale
        is_degenerate = altitude <= body_scale * DEGENERATE_ALTITUDE_BODY_SCALE_RATIO
        is_long = edge_ratio >= LONG_EDGE_BODY_SCALE_RATIO
        is_sliver = edge_ratio >= SLIVER_MIN_EDGE_BODY_SCALE_RATIO and aspect >= SLIVER_MIN_ASPECT
        if _is_repair_candidate(max_edge=max_edge, altitude=altitude, aspect=aspect, body_scale=body_scale):
            removed += 1
            removed_long += int(is_long)
            removed_sliver += int(is_sliver)
            removed_degenerate += int(is_degenerate)
            continue
        repaired_indices.extend((ia, ib, ic))

    triangle_count = len(indices) // 3
    removal_ratio = removed / max(1, triangle_count)
    if removed == 0:
        raise MeshTopologyRepairError("mesh topology repair: no repair candidates were found")
    if removal_ratio > MAX_REMOVAL_RATIO:
        raise MeshTopologyRepairError(
            f"mesh topology repair: contamination exceeds bounded repair ({removal_ratio:.6f} > {MAX_REMOVAL_RATIO:.6f})"
        )
    if len(repaired_indices) < 3:
        raise MeshTopologyRepairError("mesh topology repair: repair would remove the entire mesh")

    repaired_binary = _replace_index_accessor(
        document,
        binary,
        accessor_index=index_accessor,
        new_indices=repaired_indices,
    )
    repaired_avatar = _encode_glb(document, repaired_binary)
    try:
        validate_vrm1(repaired_avatar)
    except AvatarError as exc:
        raise MeshTopologyRepairError(f"mesh topology repair: repaired VRM is invalid: {exc}") from exc
    return repaired_avatar, {
        "triangle_count_before": triangle_count,
        "triangle_count_after": len(repaired_indices) // 3,
        "removed_triangle_count": removed,
        "removed_triangle_ratio": round(removal_ratio, 8),
        "removed_long_triangle_count": removed_long,
        "removed_sliver_triangle_count": removed_sliver,
        "removed_degenerate_triangle_count": removed_degenerate,
        "body_scale": round(body_scale, 8),
    }


def _current_revision() -> str | None:
    repo = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip().lower()
    return value if len(value) == 40 and all(ch in "0123456789abcdef" for ch in value) else None


def repair_package(source: str | Path, destination: str | Path) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if destination_path.exists():
        raise MeshTopologyRepairError(f"mesh topology repair: destination already exists: {destination_path}")
    validated = validate_package(source_path)
    before = analyze_package(source_path)

    try:
        with zipfile.ZipFile(source_path, "r") as archive:
            avatar = archive.read("avatar.vrm")
            thumbnail = archive.read("thumbnail.png")
            bodyprint = json.loads(archive.read("bodyprint.json").decode("utf-8"))
            provenance = json.loads(archive.read("provenance.json").decode("utf-8"))
            motions = {
                name: archive.read(name)
                for name in validated.payload_names
                if name.startswith("motions/")
            }
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise MeshTopologyRepairError("mesh topology repair: could not read validated source package") from exc

    repaired_avatar, repair = repair_avatar(avatar)
    pipeline = provenance.get("pipeline")
    if not isinstance(pipeline, list):
        raise MeshTopologyRepairError("mesh topology repair: provenance pipeline is invalid")
    if any(isinstance(item, dict) and item.get("stage") == "mesh-topology-repair" for item in pipeline):
        raise MeshTopologyRepairError("mesh topology repair: source package was already topology-repaired")
    pipeline.append({"stage": "mesh-topology-repair", "adapter": REPAIR_ADAPTER, "revision": REPAIR_REVISION})

    builder = validated.manifest.get("builder", {})
    builder_version = builder.get("version") if isinstance(builder, dict) else None
    if not isinstance(builder_version, str) or not builder_version:
        raise MeshTopologyRepairError("mesh topology repair: source builder version is invalid")
    build_package(
        destination_path,
        body_id=str(validated.manifest["id"]),
        name=str(validated.manifest["name"]),
        avatar_vrm=repaired_avatar,
        bodyprint=bodyprint,
        provenance=provenance,
        thumbnail_png=thumbnail,
        motions=motions,
        builder_version=builder_version,
        builder_revision=_current_revision(),
    )
    after = analyze_package(destination_path)
    if after.get("structural_pass") is not True:
        destination_path.unlink(missing_ok=True)
        raise MeshTopologyRepairError(
            "mesh topology repair: repaired package still fails topology QA; output removed"
        )

    return {
        "format": "bodyrig-mesh-topology-repair",
        "version": 1,
        "semantics": "geometry-repair-not-identity-verification",
        "source_package": str(source_path),
        "source_package_sha256": _sha256_path(source_path),
        "output_package": str(destination_path),
        "output_package_sha256": _sha256_path(destination_path),
        "repair": repair,
        "topology_before": {
            "assessment": before.get("automated_assessment"),
            "structural_pass": before.get("structural_pass"),
            "triangle_geometry": before.get("triangle_geometry"),
        },
        "topology_after": {
            "assessment": after.get("automated_assessment"),
            "structural_pass": after.get("structural_pass"),
            "triangle_geometry": after.get("triangle_geometry"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a new .mrbody with physically large bridge/sliver triangles removed; never mutates the source package."
    )
    parser.add_argument("source", help="existing BodyRig .mrbody package")
    parser.add_argument("destination", help="new create-only repaired .mrbody package")
    parser.add_argument("--report", default="", help="optional create-only repair report JSON")
    args = parser.parse_args(argv)
    report_path = Path(args.report).expanduser().resolve() if args.report else None
    if report_path is not None and report_path.exists():
        print(f"BodyRig mesh topology repair: FAIL: report already exists: {report_path}")
        return 1
    try:
        result = repair_package(args.source, args.destination)
    except (OSError, MRBodyError, MeshTopologyRepairError, ValueError) as exc:
        print(f"BodyRig mesh topology repair: FAIL: {exc}")
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload, encoding="utf-8")
        print(report_path)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
