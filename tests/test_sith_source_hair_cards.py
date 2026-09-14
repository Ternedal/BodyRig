from __future__ import annotations

import math
import sys
from pathlib import Path


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_source_hair_cards import build_cards  # noqa: E402


def _cylindrical_fixture():
    angles = 36
    rows = 5
    donor = []
    source = []
    texcoords = []
    for a in range(angles):
        theta = math.tau * a / angles
        for row in range(rows):
            y = 1.62 + row * 0.075
            donor.append((0.10 * math.cos(theta), y, 0.10 * math.sin(theta)))
            source.append((0.13 * math.cos(theta), y, 0.13 * math.sin(theta)))
            texcoords.append((a / angles, row / (rows - 1)))

    faces = []
    for a in range(angles):
        next_a = (a + 1) % angles
        for row in range(rows - 1):
            v00 = a * rows + row
            v01 = v00 + 1
            v10 = next_a * rows + row
            v11 = v10 + 1
            faces.append([(v00, v00), (v01, v01), (v10, v10)])
            faces.append([(v10, v10), (v01, v01), (v11, v11)])

    guide = {
        "selected_face_indices": list(range(len(faces))),
        "selected_vertex_indices": list(range(len(source))),
        "head_center_x": 0.0,
        "head_center_z": 0.0,
        "body_height": 2.0,
    }
    distances = [0.03] * len(source)
    nearest = list(range(len(source)))
    return donor, source, texcoords, faces, distances, nearest, guide


def test_source_guided_cards_replace_closed_shell_with_open_ribbons() -> None:
    donor, source, texcoords, faces, distances, nearest, guide = _cylindrical_fixture()

    result = build_cards(
        donor_positions=donor,
        source_positions=source,
        texcoords=texcoords,
        source_faces=faces,
        distances=distances,
        nearest_indices=nearest,
        guide=guide,
    )

    assert result["card_count"] == 36
    assert len(result["positions"]) == 36 * 5 * 2
    assert len(result["faces"]) == 36 * 4 * 2
    assert len(result["texcoords"]) == len(result["positions"])

    maximum_radius = max(math.hypot(x, z) for x, _y, z in result["positions"])
    assert maximum_radius < 0.12
    assert maximum_radius > 0.10


def test_source_guided_cards_keep_source_uv_domain() -> None:
    donor, source, texcoords, faces, distances, nearest, guide = _cylindrical_fixture()

    result = build_cards(
        donor_positions=donor,
        source_positions=source,
        texcoords=texcoords,
        source_faces=faces,
        distances=distances,
        nearest_indices=nearest,
        guide=guide,
    )

    assert all(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in result["texcoords"])
