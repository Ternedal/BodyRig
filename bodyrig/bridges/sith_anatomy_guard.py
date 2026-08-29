from __future__ import annotations

import math
from typing import Iterable, Sequence

LIMB_REGIONS = ("left_arm", "right_arm", "left_leg", "right_leg")
ALL_REGIONS = ("torso", *LIMB_REGIONS)
ANATOMY_GUARD_THRESHOLD = 0.10
STRONG_REGION_MARGIN_RATIO = 1.35
STRONG_REGION_MARGIN_SCALE = 0.02
MAX_GUARD_EXTRA_SCALE = 0.08
MAX_GUARD_DISTANCE_SCALE = 0.12
MAX_GUARD_DISTANCE_RATIO = 4.0


def joint_region(name: str) -> str:
    lowered = name.strip().lower().replace("-", "_")
    if lowered.startswith("smplx_"):
        lowered = lowered[len("smplx_") :]
    if lowered.startswith("left_"):
        if any(token in lowered for token in ("hip", "knee", "ankle", "foot", "toe")):
            return "left_leg"
        return "left_arm"
    if lowered.startswith("right_"):
        if any(token in lowered for token in ("hip", "knee", "ankle", "foot", "toe")):
            return "right_leg"
        return "right_arm"
    return "torso"


def forbidden_regions(region: str) -> set[str]:
    if region == "left_arm":
        return {"right_arm", "left_leg", "right_leg"}
    if region == "right_arm":
        return {"left_arm", "left_leg", "right_leg"}
    if region == "left_leg":
        return {"right_leg", "left_arm", "right_arm"}
    if region == "right_leg":
        return {"left_leg", "left_arm", "right_arm"}
    return set()


def forbidden_joint_indices(joint_names: Sequence[str], region: str) -> tuple[int, ...]:
    forbidden = forbidden_regions(region)
    return tuple(index for index, name in enumerate(joint_names) if joint_region(name) in forbidden)


def _point_segment_distance(
    point: Sequence[float],
    a: Sequence[float],
    b: Sequence[float],
) -> float:
    ab = tuple(float(b[i]) - float(a[i]) for i in range(3))
    ap = tuple(float(point[i]) - float(a[i]) for i in range(3))
    denominator = sum(value * value for value in ab)
    if denominator <= 1e-16:
        return math.sqrt(sum(value * value for value in ap))
    t = max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / denominator))
    closest = tuple(float(a[i]) + t * ab[i] for i in range(3))
    return math.sqrt(sum((float(point[i]) - closest[i]) ** 2 for i in range(3)))


def _segments(
    joint_positions: Sequence[Sequence[float]],
    parents: Sequence[int],
    joint_names: Sequence[str],
) -> dict[str, list[tuple[Sequence[float], Sequence[float]]]]:
    if not (len(joint_positions) == len(parents) == len(joint_names)):
        raise ValueError("anatomy guard joint topology lengths differ")
    segments: dict[str, list[tuple[Sequence[float], Sequence[float]]]] = {
        region: [] for region in ALL_REGIONS
    }
    regions = [joint_region(name) for name in joint_names]
    for child, parent in enumerate(parents):
        if parent < 0:
            continue
        if parent >= len(joint_positions):
            raise ValueError("anatomy guard parent index is outside joint topology")
        segments[regions[child]].append((joint_positions[parent], joint_positions[child]))
    for region, values in segments.items():
        if values:
            continue
        values.extend(
            (joint_positions[index], joint_positions[index])
            for index, candidate in enumerate(regions)
            if candidate == region
        )
    if any(not segments[region] for region in LIMB_REGIONS):
        raise ValueError("anatomy guard skeleton does not expose all limb regions")
    return segments


def classify_strong_limb_regions(
    points: Iterable[Sequence[float]],
    joint_positions: Sequence[Sequence[float]],
    parents: Sequence[int],
    joint_names: Sequence[str],
) -> tuple[list[str | None], float]:
    segments = _segments(joint_positions, parents, joint_names)
    coordinates = [float(value) for point in joint_positions for value in point[:3]]
    if len(coordinates) != len(joint_positions) * 3 or not all(math.isfinite(value) for value in coordinates):
        raise ValueError("anatomy guard joint coordinates are invalid")
    xs = coordinates[0::3]
    ys = coordinates[1::3]
    zs = coordinates[2::3]
    body_scale = math.sqrt(
        (max(xs) - min(xs)) ** 2
        + (max(ys) - min(ys)) ** 2
        + (max(zs) - min(zs)) ** 2
    )
    if not math.isfinite(body_scale) or body_scale <= 1e-6:
        raise ValueError("anatomy guard skeleton scale is invalid")

    result: list[str | None] = []
    for raw_point in points:
        point = tuple(float(raw_point[index]) for index in range(3))
        if not all(math.isfinite(value) for value in point):
            raise ValueError("anatomy guard reconstructed vertex is non-finite")
        distances = {
            region: min(_point_segment_distance(point, a, b) for a, b in region_segments)
            for region, region_segments in segments.items()
            if region_segments
        }
        ordered = sorted(distances.items(), key=lambda item: item[1])
        nearest_region, nearest_distance = ordered[0]
        second_distance = ordered[1][1]
        if nearest_region not in LIMB_REGIONS:
            result.append(None)
            continue
        strong = (
            second_distance >= nearest_distance * STRONG_REGION_MARGIN_RATIO
            or second_distance - nearest_distance >= body_scale * STRONG_REGION_MARGIN_SCALE
        )
        result.append(nearest_region if strong else None)
    return result, body_scale
