from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path
from typing import Any, Sequence

import sith_source_hair_extract as legacy


METHOD = "retained-sith-connected-head-shell-v2"
MIN_FACE_COUNT = legacy.MIN_FACE_COUNT
MIN_FOOTPRINT_SPAN_BODY_RATIO = 0.018
MIN_VERTICAL_SPAN_BODY_RATIO = 0.015
STRICT_SELECTOR = {
    "name": "strict-shell",
    "candidate_distance_body_ratio": legacy.MIN_DISTANCE_BODY_RATIO,
    "seed_distance_body_ratio": legacy.SEED_DISTANCE_BODY_RATIO,
    "minimum_y_body_ratio": legacy.MIN_Y_BODY_RATIO,
    "seed_y_body_ratio": legacy.SEED_Y_BODY_RATIO,
}
SHORT_HAIR_SELECTOR = {
    "name": "short-hair-fallback",
    "candidate_distance_body_ratio": 0.003,
    "seed_distance_body_ratio": 0.0025,
    "minimum_y_body_ratio": 0.76,
    "seed_y_body_ratio": 0.82,
}


class _InsufficientSelection(RuntimeError):
    pass


def _attempt_selector(
    *,
    selector: dict[str, Any],
    source: Sequence[tuple[float, float, float]],
    face_vertices: Sequence[tuple[int, int, int]],
    distances: Sequence[float],
    normalized_y: Sequence[float],
    radial: Sequence[float],
    body_height: float,
    search_radius: float,
) -> dict[str, Any]:
    candidate_distance = body_height * float(selector["candidate_distance_body_ratio"])
    seed_distance = body_height * float(selector["seed_distance_body_ratio"])
    minimum_y = float(selector["minimum_y_body_ratio"])
    seed_y = float(selector["seed_y_body_ratio"])

    candidate_vertices = {
        index
        for index in range(len(source))
        if normalized_y[index] >= minimum_y
        and radial[index] <= search_radius
        and distances[index] >= candidate_distance
    }
    seed_vertices = {
        index
        for index in range(len(source))
        if normalized_y[index] >= seed_y
        and radial[index] <= search_radius
        and distances[index] >= seed_distance
    }

    candidate_faces: list[int] = []
    seed_faces: list[int] = []
    for face_index, vertices in enumerate(face_vertices):
        in_candidate = sum(vertex in candidate_vertices for vertex in vertices)
        mean_y = sum(normalized_y[vertex] for vertex in vertices) / 3.0
        if in_candidate >= 2 and mean_y >= minimum_y:
            candidate_faces.append(face_index)
            if any(vertex in seed_vertices for vertex in vertices):
                seed_faces.append(face_index)

    if not seed_faces:
        raise _InsufficientSelection("no geometric seed")

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
        raise _InsufficientSelection(f"connected shell has {len(selected)} faces < {MIN_FACE_COUNT}")

    selected_faces = sorted(selected)
    selected_vertices = sorted({vertex for face_index in selected_faces for vertex in face_vertices[face_index]})
    xs = [source[index][0] for index in selected_vertices]
    ys = [source[index][1] for index in selected_vertices]
    zs = [source[index][2] for index in selected_vertices]
    x_span_ratio = (max(xs) - min(xs)) / body_height
    z_span_ratio = (max(zs) - min(zs)) / body_height
    vertical_span_ratio = (max(ys) - min(ys)) / body_height
    if (
        x_span_ratio < MIN_FOOTPRINT_SPAN_BODY_RATIO
        or z_span_ratio < MIN_FOOTPRINT_SPAN_BODY_RATIO
        or vertical_span_ratio < MIN_VERTICAL_SPAN_BODY_RATIO
    ):
        raise _InsufficientSelection(
            "connected shell footprint/span is too small "
            f"(x={x_span_ratio:.5f}, z={z_span_ratio:.5f}, y={vertical_span_ratio:.5f})"
        )

    selected_distances = [distances[index] for index in selected_vertices]
    selected_y = [normalized_y[index] for index in selected_vertices]
    return {
        "selected_face_indices": selected_faces,
        "selected_vertex_indices": selected_vertices,
        "distance_p50": legacy._quantile(selected_distances, 0.50),
        "distance_p95": legacy._quantile(selected_distances, 0.95),
        "distance_max": max(selected_distances),
        "minimum_y_ratio": min(selected_y),
        "maximum_y_ratio": max(selected_y),
        "seed_face_count": len(seed_faces),
        "selector": str(selector["name"]),
        "selector_thresholds": {
            "candidateDistanceBodyRatio": float(selector["candidate_distance_body_ratio"]),
            "seedDistanceBodyRatio": float(selector["seed_distance_body_ratio"]),
            "minimumYBodyRatio": minimum_y,
            "seedYBodyRatio": seed_y,
            "minimumFootprintSpanBodyRatio": MIN_FOOTPRINT_SPAN_BODY_RATIO,
            "minimumVerticalSpanBodyRatio": MIN_VERTICAL_SPAN_BODY_RATIO,
        },
        "selection_metrics": {
            "horizontalXSpanBodyRatio": x_span_ratio,
            "horizontalZSpanBodyRatio": z_span_ratio,
            "verticalSpanBodyRatio": vertical_span_ratio,
        },
    }


def select_hair_faces(
    *,
    donor_positions: Sequence[Sequence[float]],
    source_positions: Sequence[Sequence[float]],
    source_faces: Sequence[Sequence[tuple[int, int]]],
    source_to_donor_distance: Sequence[float],
) -> dict[str, Any]:
    if len(donor_positions) < 16 or len(source_positions) < 16 or not source_faces:
        raise legacy.SourceHairExtractError("hair candidate geometry is incomplete")
    if len(source_to_donor_distance) != len(source_positions):
        raise legacy.SourceHairExtractError("hair candidate distance vector does not match source geometry")

    donor = [legacy._finite_triplet(row) for row in donor_positions]
    source = [legacy._finite_triplet(row) for row in source_positions]
    distances = [legacy._distance(value) for value in source_to_donor_distance]

    y_min = min(row[1] for row in donor)
    y_max = max(row[1] for row in donor)
    body_height = y_max - y_min
    if not math.isfinite(body_height) or body_height <= 1e-6:
        raise legacy.SourceHairExtractError("hair candidate donor height is invalid")

    donor_head = [row for row in donor if (row[1] - y_min) / body_height >= 0.80]
    if len(donor_head) < 8:
        raise legacy.SourceHairExtractError("hair candidate donor head region is too small")
    center_x = legacy._median([row[0] for row in donor_head])
    center_z = legacy._median([row[2] for row in donor_head])
    donor_head_radius_values = [math.hypot(row[0] - center_x, row[2] - center_z) for row in donor_head]
    donor_head_radius = legacy._quantile(donor_head_radius_values, 0.95)
    search_radius = min(max(donor_head_radius * 1.85, body_height * 0.08), body_height * 0.25)

    normalized_y: list[float] = []
    radial: list[float] = []
    for row in source:
        normalized_y.append((row[1] - y_min) / body_height)
        radial.append(math.hypot(row[0] - center_x, row[2] - center_z))

    face_vertices: list[tuple[int, int, int]] = []
    for face in source_faces:
        if len(face) != 3:
            raise legacy.SourceHairExtractError("hair candidate source topology is not triangular")
        vertices = tuple(int(corner[0]) for corner in face)
        if any(vertex < 0 or vertex >= len(source) for vertex in vertices):
            raise legacy.SourceHairExtractError("hair candidate source face index is outside range")
        face_vertices.append(vertices)

    failures: list[str] = []
    for selector in (STRICT_SELECTOR, SHORT_HAIR_SELECTOR):
        try:
            result = _attempt_selector(
                selector=selector,
                source=source,
                face_vertices=face_vertices,
                distances=distances,
                normalized_y=normalized_y,
                radial=radial,
                body_height=body_height,
                search_radius=search_radius,
            )
        except _InsufficientSelection as exc:
            failures.append(f"{selector['name']}: {exc}")
            continue
        result.update(
            {
                "body_height": body_height,
                "head_center_x": center_x,
                "head_center_z": center_z,
                "search_radius": search_radius,
            }
        )
        return result

    raise legacy.SourceHairExtractError(
        "retained source exposes no reviewable source-derived hair shell; " + "; ".join(failures)
    )


def extract(*, workspace: Path, donor_obj: Path, output_dir: Path) -> dict[str, Any]:
    selection_holder: dict[str, Any] = {}
    original_selector = legacy.select_hair_faces

    def _capturing_selector(**kwargs: Any) -> dict[str, Any]:
        result = select_hair_faces(**kwargs)
        selection_holder.clear()
        selection_holder.update(result)
        return result

    legacy.select_hair_faces = _capturing_selector
    try:
        receipt = legacy.extract(workspace=workspace, donor_obj=donor_obj, output_dir=output_dir)
    finally:
        legacy.select_hair_faces = original_selector

    if not selection_holder:
        raise legacy.SourceHairExtractError("hair selector did not publish selection metadata")
    receipt["method"] = METHOD
    receipt["selector"] = selection_holder["selector"]
    receipt["selectorThresholds"] = selection_holder["selector_thresholds"]
    receipt["selectionMetrics"] = {
        key: round(float(value), 9)
        for key, value in selection_holder["selection_metrics"].items()
    }
    receipt_path = output_dir.expanduser().resolve() / "source-hair-candidate.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract a source-derived hair candidate with strict-first short-hair recovery."
    )
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
        f"selector={receipt['selector']} | faces={receipt['selectedFaceCount']} | "
        f"vertices={receipt['selectedVertexCount']} | p95={receipt['sourceToDonorDistanceP95']:.6f} | "
        "human_review=required"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
