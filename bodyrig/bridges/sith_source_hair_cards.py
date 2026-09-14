from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, Sequence

import sith_smplx_vrm_fitter as base
import sith_source_hair_extract as shell


FORMAT = "bodyrig-source-hair-candidate"
VERSION = 1
METHOD = "retained-sith-source-guided-hair-cards-v1"
CARD_AZIMUTH_BINS = 72
CARD_POINTS_PER_STRIP = 9
MIN_CARD_COUNT = 24
SCALP_OFFSET_BODY_RATIO = 0.0045
MAX_OFFSET_BODY_RATIO = 0.012
EXCESS_VOLUME_RETAIN = 0.22
MIN_HALF_WIDTH_BODY_RATIO = 0.0015
MAX_HALF_WIDTH_BODY_RATIO = 0.0045
UV_HALF_WIDTH = 0.003


class SourceHairCardsError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nearest_donor(torch: Any, *, query: Any, reference: Any) -> tuple[Any, Any]:
    count = int(query.shape[0])
    distances = torch.full((count,), float("inf"), dtype=torch.float32, device=query.device)
    indices = torch.full((count,), -1, dtype=torch.int64, device=query.device)
    for start in range(0, count, 1024):
        chunk = query[start:start + 1024]
        local_distance = torch.full((int(chunk.shape[0]),), float("inf"), dtype=torch.float32, device=query.device)
        local_index = torch.full((int(chunk.shape[0]),), -1, dtype=torch.int64, device=query.device)
        for ref_start in range(0, int(reference.shape[0]), 8192):
            ref = reference[ref_start:ref_start + 8192]
            matrix = torch.cdist(chunk.unsqueeze(0), ref.unsqueeze(0)).squeeze(0)
            values, offsets = torch.min(matrix, dim=1)
            better = values < local_distance
            local_distance = torch.where(better, values, local_distance)
            local_index = torch.where(better, offsets.to(torch.int64) + ref_start, local_index)
        distances[start:start + int(chunk.shape[0])] = local_distance
        indices[start:start + int(chunk.shape[0])] = local_index
    if bool(torch.any(indices < 0).item()):
        raise SourceHairCardsError("nearest donor lookup did not resolve all source vertices")
    return distances, indices


def _vertex_uv_map(
    *,
    source_faces: Sequence[Sequence[tuple[int, int]]],
    selected_faces: Sequence[int],
) -> dict[int, int]:
    result: dict[int, int] = {}
    for face_index in selected_faces:
        for vertex, uv in source_faces[face_index]:
            vertex_index = int(vertex)
            uv_index = int(uv)
            current = result.get(vertex_index)
            if current is None or uv_index < current:
                result[vertex_index] = uv_index
    return result


def _compressed_center(
    *,
    point: Sequence[float],
    donor: Sequence[float],
    distance: float,
    body_height: float,
) -> tuple[float, float, float]:
    px, py, pz = (float(value) for value in point[:3])
    qx, qy, qz = (float(value) for value in donor[:3])
    if not math.isfinite(distance) or distance <= 1e-9:
        return (px, py, pz)
    base_offset = body_height * SCALP_OFFSET_BODY_RATIO
    max_offset = body_height * MAX_OFFSET_BODY_RATIO
    if distance <= base_offset:
        target = distance
    else:
        target = min(max_offset, base_offset + (distance - base_offset) * EXCESS_VOLUME_RETAIN)
    scale = target / distance
    return (
        qx + (px - qx) * scale,
        qy + (py - qy) * scale,
        qz + (pz - qz) * scale,
    )


def build_cards(
    *,
    donor_positions: Sequence[Sequence[float]],
    source_positions: Sequence[Sequence[float]],
    texcoords: Sequence[Sequence[float]],
    source_faces: Sequence[Sequence[tuple[int, int]]],
    distances: Sequence[float],
    nearest_indices: Sequence[int],
    guide: dict[str, Any],
) -> dict[str, Any]:
    selected_faces = [int(value) for value in guide["selected_face_indices"]]
    selected_vertices = [int(value) for value in guide["selected_vertex_indices"]]
    if len(distances) != len(source_positions) or len(nearest_indices) != len(source_positions):
        raise SourceHairCardsError("hair-card nearest donor vectors do not match source geometry")
    uv_for_vertex = _vertex_uv_map(source_faces=source_faces, selected_faces=selected_faces)
    if any(vertex not in uv_for_vertex for vertex in selected_vertices):
        raise SourceHairCardsError("hair-card guide contains a vertex without source UV")

    center_x = float(guide["head_center_x"])
    center_z = float(guide["head_center_z"])
    body_height = float(guide["body_height"])
    if not math.isfinite(body_height) or body_height <= 1e-6:
        raise SourceHairCardsError("hair-card body height is invalid")

    bins: list[list[int]] = [[] for _ in range(CARD_AZIMUTH_BINS)]
    for vertex in selected_vertices:
        x, _y, z = (float(value) for value in source_positions[vertex][:3])
        angle = math.atan2(z - center_z, x - center_x)
        if angle < 0.0:
            angle += math.tau
        bucket = min(CARD_AZIMUTH_BINS - 1, int(angle / math.tau * CARD_AZIMUTH_BINS))
        bins[bucket].append(vertex)

    positions_out: list[tuple[float, float, float]] = []
    uv_out: list[tuple[float, float]] = []
    faces_out: list[tuple[int, int, int]] = []
    card_count = 0
    for bucket, vertices in enumerate(bins):
        if len(vertices) < 3:
            continue
        ordered = sorted(vertices, key=lambda index: (-float(source_positions[index][1]), index))
        sample_count = min(CARD_POINTS_PER_STRIP, len(ordered))
        sampled: list[int] = []
        for row in range(sample_count):
            offset = int(round(row * (len(ordered) - 1) / max(1, sample_count - 1)))
            vertex = ordered[offset]
            if not sampled or vertex != sampled[-1]:
                sampled.append(vertex)
        if len(sampled) < 3:
            continue

        row_vertices: list[tuple[int, int]] = []
        for row, vertex in enumerate(sampled):
            point = source_positions[vertex]
            donor_index = int(nearest_indices[vertex])
            if donor_index < 0 or donor_index >= len(donor_positions):
                raise SourceHairCardsError("hair-card guide references an invalid donor vertex")
            center = _compressed_center(
                point=point,
                donor=donor_positions[donor_index],
                distance=float(distances[vertex]),
                body_height=body_height,
            )
            rx = center[0] - center_x
            rz = center[2] - center_z
            radius = math.hypot(rx, rz)
            if radius <= 1e-8:
                angle = (bucket + 0.5) / CARD_AZIMUTH_BINS * math.tau
                tangent_x, tangent_z = -math.sin(angle), math.cos(angle)
                radius = body_height * 0.04
            else:
                tangent_x, tangent_z = -rz / radius, rx / radius
            circumference_step = math.tau * max(radius, body_height * 0.04) / CARD_AZIMUTH_BINS
            half_width = max(
                body_height * MIN_HALF_WIDTH_BODY_RATIO,
                min(body_height * MAX_HALF_WIDTH_BODY_RATIO, circumference_step * 0.47),
            )
            t = row / max(1, len(sampled) - 1)
            taper = 0.35 + 0.65 * (max(0.0, math.sin(math.pi * t)) ** 0.7)
            if row == len(sampled) - 1:
                taper = 0.12
            half_width *= taper

            left = (
                center[0] - tangent_x * half_width,
                center[1],
                center[2] - tangent_z * half_width,
            )
            right = (
                center[0] + tangent_x * half_width,
                center[1],
                center[2] + tangent_z * half_width,
            )
            uv_index = uv_for_vertex[vertex]
            if uv_index < 0 or uv_index >= len(texcoords):
                raise SourceHairCardsError("hair-card source UV index is outside range")
            u, v = (float(value) for value in texcoords[uv_index][:2])
            left_uv = (max(0.0, u - UV_HALF_WIDTH), min(1.0, max(0.0, v)))
            right_uv = (min(1.0, u + UV_HALF_WIDTH), min(1.0, max(0.0, v)))
            left_index = len(positions_out)
            positions_out.extend((left, right))
            uv_out.extend((left_uv, right_uv))
            row_vertices.append((left_index, left_index + 1))

        for row in range(len(row_vertices) - 1):
            l0, r0 = row_vertices[row]
            l1, r1 = row_vertices[row + 1]
            faces_out.append((l0, l1, r0))
            faces_out.append((r0, l1, r1))
        card_count += 1

    if card_count < MIN_CARD_COUNT:
        raise SourceHairCardsError(
            f"source guide produced too few usable hair cards ({card_count} < {MIN_CARD_COUNT})"
        )
    if len(faces_out) < MIN_CARD_COUNT * 4:
        raise SourceHairCardsError("source guide produced too little hair-card geometry")
    return {
        "positions": positions_out,
        "texcoords": uv_out,
        "faces": faces_out,
        "card_count": card_count,
    }


def _write_cards_obj(
    path: Path,
    *,
    positions: Sequence[Sequence[float]],
    texcoords: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    material_name: str | None,
    mtl_name: str,
) -> None:
    if len(positions) != len(texcoords):
        raise SourceHairCardsError("hair-card vertex/UV counts differ")
    lines = [f"mtllib {mtl_name}"]
    if material_name:
        lines.append(f"usemtl {material_name}")
    for x, y, z in positions:
        lines.append(f"v {float(x):.9f} {float(y):.9f} {float(z):.9f}")
    for u, v in texcoords:
        lines.append(f"vt {float(u):.9f} {float(v):.9f}")
    for face in faces:
        if len(face) != 3:
            raise SourceHairCardsError("hair-card output topology is not triangular")
        tokens = [f"{int(index) + 1}/{int(index) + 1}" for index in face]
        lines.append("f " + " ".join(tokens))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _dominant_material(materials: Sequence[str | None], selected_faces: Sequence[int]) -> str | None:
    counts: dict[str, int] = {}
    for face_index in selected_faces:
        if face_index < 0 or face_index >= len(materials):
            continue
        name = materials[face_index]
        if name:
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda name: (counts[name], name))


def extract(*, workspace: Path, donor_obj: Path, output_dir: Path) -> dict[str, Any]:
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise SourceHairCardsError(f"numpy and torch are required for source-guided hair cards: {exc}") from exc
    if not torch.cuda.is_available():
        raise SourceHairCardsError("source-guided hair cards require CUDA")

    workspace = workspace.expanduser().resolve()
    donor_obj = donor_obj.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise SourceHairCardsError(f"hair-card output already exists: {output_dir}")
    stage = workspace / "sith-input-v1"
    reconstruction_path = stage / "reconstruction.json"
    try:
        reconstruction = json.loads(reconstruction_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceHairCardsError("retained reconstruction evidence is unreadable") from exc
    details = reconstruction.get("reconstruction") if isinstance(reconstruction, dict) else None
    if not isinstance(details, dict):
        raise SourceHairCardsError("retained reconstruction detail block is missing")
    texture_name = details.get("mesh_texture_name")
    if not isinstance(texture_name, str) or Path(texture_name).name != texture_name:
        raise SourceHairCardsError("retained reconstruction texture name is invalid")
    source_obj = stage / "meshes" / "000_reco.obj"
    source_mtl = stage / "meshes" / "000.mtl"
    source_texture = stage / "meshes" / texture_name
    for artifact in (reconstruction_path, source_obj, source_mtl, source_texture, donor_obj):
        if not artifact.is_file():
            raise SourceHairCardsError(f"hair-card input is missing: {artifact}")

    donor_positions = base._parse_positions(donor_obj)
    source_positions, texcoords, source_faces = base._parse_textured_obj(source_obj)
    device = torch.device("cuda")
    donor_tensor = torch.tensor(np.asarray(donor_positions, dtype=np.float32), device=device)
    source_tensor = torch.tensor(np.asarray(source_positions, dtype=np.float32), device=device)
    with torch.no_grad():
        distance_tensor, nearest_tensor = _nearest_donor(torch, query=source_tensor, reference=donor_tensor)
    distances = distance_tensor.detach().cpu().tolist()
    nearest_indices = nearest_tensor.detach().cpu().tolist()
    guide = shell.select_hair_faces(
        donor_positions=donor_positions,
        source_positions=source_positions,
        source_faces=source_faces,
        source_to_donor_distance=distances,
    )
    cards = build_cards(
        donor_positions=donor_positions,
        source_positions=source_positions,
        texcoords=texcoords,
        source_faces=source_faces,
        distances=distances,
        nearest_indices=nearest_indices,
        guide=guide,
    )
    face_materials = shell._source_face_materials(source_obj)
    if len(face_materials) != len(source_faces):
        raise SourceHairCardsError("source OBJ face/material sequence is inconsistent")
    material_name = _dominant_material(face_materials, guide["selected_face_indices"])

    output_dir.mkdir(parents=True, exist_ok=False)
    hair_obj = output_dir / "hair_source.obj"
    output_mtl = output_dir / "000.mtl"
    output_texture = output_dir / texture_name
    _write_cards_obj(
        hair_obj,
        positions=cards["positions"],
        texcoords=cards["texcoords"],
        faces=cards["faces"],
        material_name=material_name,
        mtl_name=output_mtl.name,
    )
    shutil.copyfile(source_mtl, output_mtl)
    shutil.copyfile(source_texture, output_texture)

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "method": METHOD,
        "sourceReconstructionSha256": _sha256(reconstruction_path),
        "sourceMeshSha256": _sha256(source_obj),
        "sourceMaterialSha256": _sha256(source_mtl),
        "sourceTextureSha256": _sha256(source_texture),
        "donorObjSha256": _sha256(donor_obj),
        "hairObjSha256": _sha256(hair_obj),
        "hairMaterialSha256": _sha256(output_mtl),
        "hairTextureSha256": _sha256(output_texture),
        "selectedFaceCount": len(cards["faces"]),
        "selectedVertexCount": len(cards["positions"]),
        "seedFaceCount": int(guide["seed_face_count"]),
        "selectionMode": str(guide["selection_mode"]),
        "minimumDistanceBodyRatio": round(float(guide["minimum_distance_body_ratio"]), 9),
        "seedDistanceBodyRatio": round(float(guide["seed_distance_body_ratio"]), 9),
        "minimumYBodyRatio": round(float(guide["minimum_y_body_ratio"]), 9),
        "seedYBodyRatio": round(float(guide["seed_y_body_ratio"]), 9),
        "headFootprintSpanBodyRatio": round(float(guide["head_footprint_span_body_ratio"]), 9),
        "verticalSpanBodyRatio": round(float(guide["vertical_span_body_ratio"]), 9),
        "bodyHeight": round(float(guide["body_height"]), 9),
        "headSearchRadius": round(float(guide["search_radius"]), 9),
        "sourceToDonorDistanceP50": round(float(guide["distance_p50"]), 9),
        "sourceToDonorDistanceP95": round(float(guide["distance_p95"]), 9),
        "sourceToDonorDistanceMax": round(float(guide["distance_max"]), 9),
        "minimumBodyHeightRatio": round(float(guide["minimum_y_ratio"]), 9),
        "maximumBodyHeightRatio": round(float(guide["maximum_y_ratio"]), 9),
        "sourceDerived": True,
        "generativeGeometry": True,
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
    parser = argparse.ArgumentParser(description="Build source-guided hair cards from retained SiTH geometry.")
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
        print(f"BodyRig source-guided hair cards: FAIL: {exc}")
        return 1
    print(
        "BodyRig source-guided hair cards: PASS | "
        f"faces={receipt['selectedFaceCount']} | vertices={receipt['selectedVertexCount']} | "
        f"p95={receipt['sourceToDonorDistanceP95']:.6f} | human_review=required"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
