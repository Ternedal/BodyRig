from __future__ import annotations

import sys
from pathlib import Path

import pytest


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_source_hair_extract import SourceHairExtractError  # noqa: E402
from sith_source_hair_extract_v2 import (  # noqa: E402
    METHOD,
    MIN_FOOTPRINT_SPAN_BODY_RATIO,
    MIN_VERTICAL_SPAN_BODY_RATIO,
    select_hair_faces,
)


def _donor() -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for y in (0.0, 0.4, 0.8, 1.2, 1.6, 1.8, 2.0):
        for x in (-0.10, -0.05, 0.05, 0.10):
            for z in (-0.08, 0.08):
                points.append((x, y, z))
    return points


def _hair_grid(*, compact: bool = False) -> tuple[list[tuple[float, float, float]], list[list[tuple[int, int]]]]:
    vertices: list[tuple[float, float, float]] = []
    rows = 5
    cols = 6
    x_step = 0.008 if compact else 0.044
    z_step = 0.002 if compact else 0.012
    y_step = 0.006 if compact else 0.09
    x_start = -(cols - 1) * x_step / 2.0
    for row in range(rows):
        y = 1.55 + row * y_step
        for col in range(cols):
            x = x_start + col * x_step
            z = 0.12 + z_step * (row + col * 0.25)
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


def _select(source, faces, distance: float):
    return select_hair_faces(
        donor_positions=_donor(),
        source_positions=source,
        source_faces=faces,
        source_to_donor_distance=[distance] * len(source),
    )


def test_v2_method_name_invalidates_v1_candidate_method() -> None:
    assert METHOD == "retained-sith-connected-head-shell-v2"


def test_strict_selector_wins_when_original_shell_is_reviewable() -> None:
    source, faces = _hair_grid()

    result = _select(source, faces, 0.035)

    assert result["selector"] == "strict-shell"
    assert len(result["selected_face_indices"]) == 40
    assert result["selector_thresholds"]["candidateDistanceBodyRatio"] == pytest.approx(0.008)
    assert result["selection_metrics"]["horizontalXSpanBodyRatio"] >= MIN_FOOTPRINT_SPAN_BODY_RATIO
    assert result["selection_metrics"]["horizontalZSpanBodyRatio"] >= MIN_FOOTPRINT_SPAN_BODY_RATIO
    assert result["selection_metrics"]["verticalSpanBodyRatio"] >= MIN_VERTICAL_SPAN_BODY_RATIO


def test_short_hair_fallback_recovers_close_but_meaningful_top_shell() -> None:
    source, faces = _hair_grid()

    result = _select(source, faces, 0.008)

    assert result["selector"] == "short-hair-fallback"
    assert len(result["selected_face_indices"]) == 40
    thresholds = result["selector_thresholds"]
    assert thresholds["candidateDistanceBodyRatio"] == pytest.approx(0.003)
    assert thresholds["seedDistanceBodyRatio"] == pytest.approx(0.0025)
    assert thresholds["minimumYBodyRatio"] == pytest.approx(0.76)
    assert thresholds["seedYBodyRatio"] == pytest.approx(0.82)


def test_short_hair_fallback_still_rejects_skin_close_to_donor() -> None:
    source, faces = _hair_grid()

    with pytest.raises(SourceHairExtractError, match="no reviewable source-derived hair shell"):
        _select(source, faces, 0.002)


def test_tiny_connected_head_fragment_is_not_reviewable_even_with_many_faces() -> None:
    source, faces = _hair_grid(compact=True)

    with pytest.raises(SourceHairExtractError, match="footprint/span is too small"):
        _select(source, faces, 0.035)
