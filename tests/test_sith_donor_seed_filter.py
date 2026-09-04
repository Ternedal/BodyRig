from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_donor_module(repo: Path):
    bridges = repo / "bodyrig" / "bridges"
    path = bridges / "sith_smplx_vrm_fitter_donor.py"
    previous = list(sys.path)
    try:
        sys.path.insert(0, str(bridges))
        spec = importlib.util.spec_from_file_location("bodyrig_donor_seed_filter_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = previous


def test_dead_textured_vertices_are_not_eligible_donor_uv_seeds() -> None:
    repo = Path(__file__).resolve().parents[1]
    donor = _load_donor_module(repo)

    # Vertices 0/1/2 are textured but their only face has zero geometric area.
    # Vertices 3/4/5 form the nearest actual source surface and must remain
    # eligible. The fitter's tiled nearest-neighbour search is then constrained
    # to this usable set before any donor corner reaches UV projection.
    positions = [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.01, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.01, 1.0, 0.0),
    ]
    faces = [
        [(0, 0), (1, 1), (2, 2)],
        [(3, 3), (4, 4), (5, 5)],
    ]
    uv_map = {index: index for index in range(6)}

    usable = donor._usable_textured_source_vertices(
        source_positions=positions,
        source_faces=faces,
        source_uv_map=uv_map,
    )

    assert usable == {3, 4, 5}


def test_nearest_seed_search_is_explicitly_constrained_to_usable_vertices() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "bodyrig" / "bridges" / "sith_smplx_vrm_fitter_donor.py").read_text(encoding="utf-8")

    assert "usable_source_vertices = _usable_textured_source_vertices(" in source
    assert "usable_source_vertices=usable_source_vertices" in source
    assert "valid_source = sorted(vertex for vertex in source_uv_map if vertex in usable_source_vertices)" in source
    assert "source_posed[valid_index]" in source
