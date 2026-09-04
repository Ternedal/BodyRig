from __future__ import annotations

import sys
from pathlib import Path

import pytest


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_source_hair_extract import SourceHairExtractError, select_hair_faces  # noqa: E402


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


def test_hair_selector_keeps_connected_external_head_shell() -> None:
    source, faces = _hair_grid()
    distances = [0.035] * len(source)

    result = select_hair_faces(
        donor_positions=_donor(),
        source_positions=source,
        source_faces=faces,
        source_to_donor_distance=distances,
    )

    assert len(result["selected_face_indices"]) == 40
    assert len(result["selected_vertex_indices"]) == 30
    assert result["seed_face_count"] > 0
    assert result["distance_p95"] == pytest.approx(0.035)
    assert result["minimum_y_ratio"] >= 0.60


def test_hair_selector_rejects_skin_close_to_donor_as_hair() -> None:
    source, faces = _hair_grid()
    distances = [0.002] * len(source)

    with pytest.raises(SourceHairExtractError, match="no geometric hair seed"):
        select_hair_faces(
            donor_positions=_donor(),
            source_positions=source,
            source_faces=faces,
            source_to_donor_distance=distances,
        )


def test_hair_selector_does_not_bridge_disconnected_candidate_island() -> None:
    source, faces = _hair_grid()
    offset = len(source)
    island = [(-0.05, 1.30, 0.10), (0.0, 1.30, 0.10), (0.05, 1.30, 0.10), (0.0, 1.36, 0.10)]
    source.extend(island)
    faces.extend(
        [
            [(offset, offset), (offset + 1, offset + 1), (offset + 3, offset + 3)],
            [(offset + 1, offset + 1), (offset + 2, offset + 2), (offset + 3, offset + 3)],
        ]
    )
    distances = [0.035] * len(source)

    result = select_hair_faces(
        donor_positions=_donor(),
        source_positions=source,
        source_faces=faces,
        source_to_donor_distance=distances,
    )

    assert len(result["selected_face_indices"]) == 40
    assert max(result["selected_face_indices"]) < 40
