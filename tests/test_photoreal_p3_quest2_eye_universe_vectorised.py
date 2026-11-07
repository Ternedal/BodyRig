"""Oracle tests: the numpy component vertex universe equals the per-corner loops.

`_eye_arrays` builds the sorted unique vertex universe of the selected eye
faces and remaps every corner into it. `_component_vertex_universe` does
that with np.unique; the per-corner loops are kept as
`_component_vertex_universe_reference` and are both the oracle and the
fallback for irregular inputs.
"""

from __future__ import annotations

import random

import numpy as np

from bodyrig.photoreal_p3_quest2_eye_component import (
    _component_vertex_universe,
    _component_vertex_universe_reference,
)


def _random_universe(rng: random.Random):
    vertex_count = rng.randrange(4, 400)
    face_count = rng.randrange(1, 300)
    indices = [rng.randrange(0, vertex_count) for _ in range(face_count * 3)]
    selected = sorted(rng.sample(range(face_count), rng.randrange(1, face_count + 1)))
    if rng.random() < 0.3:
        rng.shuffle(selected)  # callers pass index order, but the universe must not depend on it
    return indices, selected


def test_universe_matches_reference_on_random_meshes() -> None:
    rng = random.Random(1106)
    for _ in range(300):
        indices, selected = _random_universe(rng)
        expected = _component_vertex_universe_reference(indices, selected)
        actual = _component_vertex_universe(np, indices, selected)
        assert actual == expected
        vertices, local = actual
        assert vertices == sorted(set(vertices))
        assert len(local) == 3 * len(selected)
        assert all(type(value) is int for value in vertices)
        assert all(type(value) is int for value in local)
        # The remap round-trips: local index -> universe -> original corner vertex.
        assert [vertices[value] for value in local] == [indices[face * 3 + offset] for face in selected for offset in range(3)]


def test_universe_accepts_numpy_integer_inputs_identically() -> None:
    rng = random.Random(2)
    indices, selected = _random_universe(rng)
    expected = _component_vertex_universe_reference(indices, selected)
    for dtype in (np.int32, np.uint32, np.int64, np.uint16):
        assert _component_vertex_universe(np, np.asarray(indices, dtype=dtype), np.asarray(selected, dtype=dtype)) == expected
    assert _component_vertex_universe(np, tuple(indices), tuple(selected)) == expected


def test_universe_falls_back_to_reference_for_irregular_inputs() -> None:
    indices = [0, 1, 2, 2, 3, 0]
    # Floats are coerced by the reference loops (int()) and must give the same result.
    assert _component_vertex_universe(np, [0.0, 1.0, 2.0, 2.0, 3.0, 0.0], [0, 1]) == _component_vertex_universe_reference(indices, [0, 1])
    # Nothing selected: an empty universe, exactly like the reference.
    assert _component_vertex_universe(np, indices, []) == ([], [])
    assert _component_vertex_universe_reference(indices, []) == ([], [])


def test_universe_shared_vertices_between_faces_are_deduplicated() -> None:
    # Two faces share an edge (1, 2): the universe has four vertices, the
    # second face's corners remap onto the first face's entries.
    indices = [5, 1, 2, 2, 1, 9]
    assert _component_vertex_universe(np, indices, [0, 1]) == ([1, 2, 5, 9], [2, 0, 1, 1, 0, 3])
    assert _component_vertex_universe_reference(indices, [0, 1]) == ([1, 2, 5, 9], [2, 0, 1, 1, 0, 3])
