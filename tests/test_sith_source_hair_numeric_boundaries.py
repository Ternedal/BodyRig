from __future__ import annotations

import sys
from pathlib import Path

import pytest


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_source_hair_extract import SourceHairExtractError, select_hair_faces  # noqa: E402


class FloatOnce:
    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def __float__(self) -> float:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("numeric value was converted more than once")
        return float(self.value)


def _donor() -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for y in (0.0, 0.4, 0.8, 1.2, 1.6, 1.8, 2.0):
        for x in (-0.10, -0.05, 0.05, 0.10):
            for z in (-0.08, 0.08):
                points.append((x, y, z))
    return points


def _hair_grid() -> tuple[list[tuple[float, float, float]], list[list[tuple[int, int]]]]:
    vertices: list[tuple[float, float, float]] = []
    rows = 5
    cols = 6
    for row in range(rows):
        y = 1.55 + row * 0.09
        for col in range(cols):
            x = -0.11 + col * 0.044
            z = 0.12 + 0.01 * row
            vertices.append((x, y, z))
    faces: list[list[tuple[int, int]]] = []
    for row in range(rows - 1):
        for col in range(cols - 1):
            a = row * cols + col
            b = a + 1
            c = a + cols
            d = c + 1
            faces.append([(a, a), (c, c), (b, b)])
            faces.append([(b, b), (c, c), (d, d)])
    return vertices, faces


def _select(
    donor: list[tuple[float, float, float]],
    source: list[tuple[float, float, float]],
    faces: list[list[tuple[int, int]]],
    distances: list[float],
):
    return select_hair_faces(
        donor_positions=donor,
        source_positions=source,
        source_faces=faces,
        source_to_donor_distance=distances,
    )


def test_selector_normalizes_donor_coordinate_overflow() -> None:
    donor = _donor()
    donor[0] = (10**400, 0.0, 0.0)
    source, faces = _hair_grid()

    with pytest.raises(SourceHairExtractError, match="hair candidate geometry is non-finite"):
        _select(donor, source, faces, [0.035] * len(source))


def test_selector_normalizes_source_coordinate_overflow() -> None:
    donor = _donor()
    source, faces = _hair_grid()
    source[0] = (10**400, source[0][1], source[0][2])

    with pytest.raises(SourceHairExtractError, match="hair candidate geometry is non-finite"):
        _select(donor, source, faces, [0.035] * len(source))


def test_selector_normalizes_distance_overflow() -> None:
    donor = _donor()
    source, faces = _hair_grid()
    distances = [0.035] * len(source)
    distances[0] = 10**400

    with pytest.raises(SourceHairExtractError, match="hair candidate distances are invalid"):
        _select(donor, source, faces, distances)


def test_selector_preserves_valid_selection() -> None:
    donor = _donor()
    source, faces = _hair_grid()

    result = _select(donor, source, faces, [0.035] * len(source))

    assert len(result["selected_face_indices"]) == 40
    assert len(result["selected_vertex_indices"]) == 30
    assert result["seed_face_count"] > 0
    assert result["distance_p50"] == pytest.approx(0.035)
    assert result["distance_p95"] == pytest.approx(0.035)
    assert result["minimum_y_ratio"] >= 0.60


def test_selector_converts_input_numerics_exactly_once() -> None:
    donor_raw = _donor()
    source_raw, faces = _hair_grid()
    donor = [[FloatOnce(value) for value in point] for point in donor_raw]
    source = [[FloatOnce(value) for value in point] for point in source_raw]
    distances = [FloatOnce(0.035) for _ in source]

    result = select_hair_faces(
        donor_positions=donor,
        source_positions=source,
        source_faces=faces,
        source_to_donor_distance=distances,
    )

    assert len(result["selected_face_indices"]) == 40
    assert all(value.calls == 1 for point in donor for value in point)
    assert all(value.calls == 1 for point in source for value in point)
    assert all(value.calls == 1 for value in distances)
