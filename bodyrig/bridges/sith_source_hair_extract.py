from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Sequence

import sith_smplx_vrm_fitter as base


FORMAT = "bodyrig-source-hair-candidate"
VERSION = 1
MIN_FACE_COUNT = 32
MIN_DISTANCE_BODY_RATIO = 0.008
SEED_DISTANCE_BODY_RATIO = 0.006
MIN_Y_BODY_RATIO = 0.60
SEED_Y_BODY_RATIO = 0.79


class SourceHairExtractError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise SourceHairExtractError("hair candidate metric has no values")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) for value in ordered):
        raise SourceHairExtractError("hair candidate metric is non-finite")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _median(values: Sequence[float]) -> float:
    return _quantile(values, 0.5)


def select_hair_faces(
    *,
    donor_positions: Sequence[Sequence[float]],
    source_positions: Sequence[Sequence[float]],
    source_faces: Sequence[Sequence[tuple[int, int]]],
    source_to_donor_distance: Sequence[float],
) -> dict[str, Any]:
    if len(donor_positions) < 16 or len(source_positions) < 16 or not source_faces:
        raise SourceHairExtractError("hair candidate geometry is incomplete")
    if len(source_to_donor_distance) != len(source_positions):
        raise SourceHairExtractError("hair candidate distance vector does not match source geometry")

    donor = [tuple(float(value) for value in row[:3]) for row in donor_positions]
    source = [tuple(float(value) for value in row[:3]) for row in source_positions]
    distances = [float(value) for value in source_to_donor_distance]
    if any(len(row) != 3 or not all(math.isfinite(value) for value in row) for row in donor + source):
        raise SourceHairExtractError("hair candidate geometry is non-finite")
    if any(not math.isfinite(value) or value < 0.0 for value in distances):
        raise SourceHairExtractError("hair candidate distances are invalid")

    y_min = min(row[1] for row in donor)
    y_max = max(row[1] for row in donor)
    body_height = y_max - y_min
    if not math.isfinite(body_height) or body_height <= 1e-6:
        raise SourceHairExtractError("hair candidate donor height is invalid")

    donor_head = [row for row in donor if (row[1] - y_min) / body_height >= 0.80]
    if len(donor_head) < 8:
        raise SourceHairExtractError("hair candidate donor head region is too small")
    center_x = _median([row[0] for row in donor_head])
    center_z = _median([row[2] for row in donor_head])
    donor_head_radius_values = [math.hypot(row[0] - center_x, row[2] - center_z) for row in donor_head]
    donor_head_radius = _quantile(donor_head_radius_values, 0.95)
    search_radius = min(max(donor_head_radius * 1.85, body_height * 0.08), body_height * 0.25)

    min_distance = body_height * MIN_DISTANCE_BODY_RATIO
    seed_distance = body_height * SEED_DISTANCE_BODY_RATIO
    candidate_vertices: set[int] = set()
    seed_vertices: set[int] = set()
    normalized_y: list[float] = []
    radial: list[float] = []
    for index, row in enumerate(source):
        yn = (row[1] - y_min) / body_height
        radius = math.hypot(row[0] - center_x, row[2] - center_z)
        normalized_y.append(yn)
        radial.append(radius)
        if yn >= MIN_Y_BODY_RATIO and radius <= search_radius and distances[index] >= min_distance:
            candidate_vertices.add(index)
        if yn >= SEED_Y_BODY_RATIO and radius <= search_radius and distances[index] >= seed_distance:
            seed_vertices.add(index)

    candidate_faces: list[int] = []
    seed_faces: list[int] = []
    face_vertices: list[tuple[int, int, int]] = []
    for face_index, face in enumerate(source_faces):
        if len(face) != 3:
            raise SourceHairExtractError("hair candidate source topology is not triangular")
        vertices = tuple(int(corner[0]) for corner in face)
        if any(vertex < 0 or vertex >= len(source) for vertex in vertices):
            raise SourceHairExtractError("hair candidate source face index is outside range")
        face_vertices.append(vertices)
        in_candidate = sum(vertex in candidate_vertices for vertex in vertices)
        mean_y = sum(normalized_y[vertex] for vertex in vertices) / 3.0
        if in_candidate >= 2 and mean_y >= MIN_Y_BODY_RATIO:
            candidate_faces.append(face_index)
            if any(vertex in seed_vertices for vertex in vertices):
                seed_faces.append(face_index)

    if not seed_faces:
        raise SourceHairExtractError("retained source exposes no geometric hair seed above the fitted head")

    by_vertex: dict[int, list[int]] = {}
    candidate_set = set(candidate_faces)
    for face_index in candidate_faces:
        for vertex in face_vertices[face_index]:
            by_vertex.setdefault(vertex, []).append(face_index)

    selected: set[int] = set(seed_faces)
    queue: deque[int] = deque(seed_faces)
    while queue:
        face_index = queue.popleft()
        for vertex in face_vertices[face_index]:
            for neighbor in by_vertex.get(vertex, []):
                if neighbor in candidate_set and neighbor not in selected:
                    selected.add(neighbor)
                    queue.append(neighbor)

    if len(selected) < MIN_FACE_COUNT:
        raise SourceHairExtractError(
            f"source-derived hair shell is too small for review ({len(selected)} faces < {MIN_FACE_COUNT})"
        )

    selected_faces = sorted(selected)
    selected_vertices = sorted({vertex for face_index in selected_faces for vertex in face_vertices[face_index]})
    selected_distances = [distances[index] for index in selected_vertices]
    selected_y = [normalized_y[index] for index in selected_vertices]
    return {
        "selected_face_indices": selected_faces,
        "selected_vertex_indices": selected_vertices,
        "body_height": body_height,
        "head_center_x": center_x,
        "head_center_z": center_z,
        "search_radius": search_radius,
        "distance_p50": _quantile(selected_distances, 0.50),
        "distance_p95": _quantile(selected_distances, 0.95),
        "distance_max": max(selected_distances),
        "minimum_y_ratio": min(selected_y),
        "maximum_y_ratio": max(selected_y),
        "seed_face_count": len(seed_faces),
    }


def _source_face_materials(path: Path) -> list[str | None]:
    materials: list[str | None] = []
    active: str | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceHairExtractError("source OBJ is unreadable while resolving materials") from exc
    for line in lines:
        if line.startswith("usemtl "):
            value = line[7:].strip()
            active = value or None
        elif line.startswith("f "):
            materials.append(active)
    return materials


def _write_selected_obj(
    path: Path,
    *,
    source_positions: Sequence[Sequence[float]],
    texcoords: Sequence[Sequence[float]],
    source_faces: Sequence[Sequence[tuple[int, int]]],
    selected_faces: Sequence[int],
    face_materials: Sequence[str | None],
    mtl_name: str,
) -> None:
    used_vertices = sorted({int(corner[0]) for face_index in selected_faces for corner in source_faces[face_index]})
    used_uvs = sorted({int(corner[1]) for face_index in selected_faces for corner in source_faces[face_index]})
    vertex_map = {value: index + 1 for index, value in enumerate(used_vertices)}
    uv_map = {value: index + 1 for index, value in enumerate(used_uvs)}
    lines = [f"mtllib {mtl_name}"]
    for index in used_vertices:
        x, y, z = source_positions[index]
        lines.append(f"v {float(x):.9f} {float(y):.9f} {float(z):.9f}")
    for index in used_uvs:
        u, v = texcoords[index]
        lines.append(f"vt {float(u):.9f} {float(v):.9f}")
    active_material: str | None = None
    for face_index in selected_faces:
        material = face_materials[face_index] if face_index < len(face_materials) else None
        if material != active_material and material is not None:
            lines.append(f"usemtl {material}")
            active_material = material
        corners = source_faces[face_index]
        tokens = [f"{vertex_map[int(vertex)]}/{uv_map[int(uv)]}" for vertex, uv in corners]
        lines.append("f " + " ".join(tokens))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _nearest_distances(torch: Any, *, query: Any, reference: Any) -> Any:
    result = torch.empty((int(query.shape[0]),), dtype=torch.float32, device=query.device)
    for start in range(0, int(query.shape[0]), 1024):
        chunk = query[start:start + 1024]
        local = torch.full((int(chunk.shape[0]),), float("inf"), dtype=torch.float32, device=query.device)
        for ref_start in range(0, int(reference.shape[0]), 8192):
            ref = reference[ref_start:ref_start + 8192]
            distance = torch.cdist(chunk.unsqueeze(0), ref.unsqueeze(0)).squeeze(0)
            local = torch.minimum(local, torch.min(distance, dim=1).values)
        result[start:start + int(chunk.shape[0])] = local
    return result


def extract(*, workspace: Path, donor_obj: Path, output_dir: Path) -> dict[str, Any]:
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise SourceHairExtractError(f"numpy and torch are required for source hair extraction: {exc}") from exc
    if not torch.cuda.is_available():
        raise SourceHairExtractError("source hair extraction requires CUDA")
    workspace = workspace.expanduser().resolve()
    donor_obj = donor_obj.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise SourceHairExtractError(f"hair candidate output already exists: {output_dir}")

    stage = workspace / "sith-input-v1"
    reconstruction_path = stage / "reconstruction.json"
    try:
        reconstruction = json.loads(reconstruction_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceHairExtractError("retained reconstruction evidence is unreadable") from exc
    details = reconstruction.get("reconstruction") if isinstance(reconstruction, dict) else None
    if not isinstance(details, dict):
        raise SourceHairExtractError("retained reconstruction detail block is missing")
    texture_name = details.get("mesh_texture_name")
    if not isinstance(texture_name, str) or Path(texture_name).name != texture_name:
        raise SourceHairExtractError("retained reconstruction texture name is invalid")
    source_obj = stage / "meshes" / "000_reco.obj"
    source_mtl = stage / "meshes" / "000.mtl"
    source_texture = stage / "meshes" / texture_name
    for artifact in (reconstruction_path, source_obj, source_mtl, source_texture, donor_obj):
        if not artifact.is_file():
            raise SourceHairExtractError(f"hair extraction input is missing: {artifact}")

    donor_positions = base._parse_positions(donor_obj)
    source_positions, texcoords, source_faces = base._parse_textured_obj(source_obj)
    device = torch.device("cuda")
    donor_tensor = torch.tensor(np.asarray(donor_positions, dtype=np.float32), device=device)
    source_tensor = torch.tensor(np.asarray(source_positions, dtype=np.float32), device=device)
    with torch.no_grad():
        distance = _nearest_distances(torch, query=source_tensor, reference=donor_tensor).detach().cpu().tolist()
    selection = select_hair_faces(
        donor_positions=donor_positions,
        source_positions=source_positions,
        source_faces=source_faces,
        source_to_donor_distance=distance,
    )
    face_materials = _source_face_materials(source_obj)
    if len(face_materials) != len(source_faces):
        raise SourceHairExtractError("source OBJ face/material sequence is inconsistent")

    output_dir.mkdir(parents=True, exist_ok=False)
    hair_obj = output_dir / "hair_source.obj"
    output_mtl = output_dir / "000.mtl"
    output_texture = output_dir / texture_name
    _write_selected_obj(
        hair_obj,
        source_positions=source_positions,
        texcoords=texcoords,
        source_faces=source_faces,
        selected_faces=selection["selected_face_indices"],
        face_materials=face_materials,
        mtl_name=output_mtl.name,
    )
    shutil.copyfile(source_mtl, output_mtl)
    shutil.copyfile(source_texture, output_texture)

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "method": "retained-sith-connected-head-shell-v1",
        "sourceReconstructionSha256": _sha256(reconstruction_path),
        "sourceMeshSha256": _sha256(source_obj),
        "sourceMaterialSha256": _sha256(source_mtl),
        "sourceTextureSha256": _sha256(source_texture),
        "donorObjSha256": _sha256(donor_obj),
        "hairObjSha256": _sha256(hair_obj),
        "hairMaterialSha256": _sha256(output_mtl),
        "hairTextureSha256": _sha256(output_texture),
        "selectedFaceCount": len(selection["selected_face_indices"]),
        "selectedVertexCount": len(selection["selected_vertex_indices"]),
        "seedFaceCount": selection["seed_face_count"],
        "bodyHeight": round(float(selection["body_height"]), 9),
        "headSearchRadius": round(float(selection["search_radius"]), 9),
        "sourceToDonorDistanceP50": round(float(selection["distance_p50"]), 9),
        "sourceToDonorDistanceP95": round(float(selection["distance_p95"]), 9),
        "sourceToDonorDistanceMax": round(float(selection["distance_max"]), 9),
        "minimumBodyHeightRatio": round(float(selection["minimum_y_ratio"]), 9),
        "maximumBodyHeightRatio": round(float(selection["maximum_y_ratio"]), 9),
        "sourceDerived": True,
        "generativeGeometry": False,
        "bodyTopologyModified": False,
        "candidateBinding": "head-accessory-review-only",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    (output_dir / "source-hair-candidate.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract a source-derived hair-shell candidate from retained SiTH geometry.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--donor-obj", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = extract(
            workspace=Path(args.workspace),
            donor_obj=Path(args.donor_obj),
            output_dir=Path(args.output_dir),
        )
    except Exception as exc:
        print(f"BodyRig source hair extraction: FAIL: {exc}")
        return 1
    print(
        "BodyRig source hair extraction: PASS | "
        f"faces={receipt['selectedFaceCount']} | vertices={receipt['selectedVertexCount']} | "
        f"p95={receipt['sourceToDonorDistanceP95']:.6f} | human_review=required"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
