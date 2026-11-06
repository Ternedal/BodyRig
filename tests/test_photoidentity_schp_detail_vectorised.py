"""Oracle tests: the numpy SCHP map/stats paths equal the per-pixel loops.

`_normalize_map` and `_stats` are the two per-pixel Python loops behind every
SCHP detail claim (one 512x512 map per candidate frame). The vectorised paths
must produce the same normalised rows, the same counts, the same boxes in the
same dict insertion order, and the same error for the first offending pixel.
The original loops are kept here as the oracle.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from bodyrig.photoidentity_schp_contract import LABELS
from bodyrig.photoidentity_schp_detail import (
    PhotoIdentitySchpDetailError,
    _normalize_map,
    _normalize_rows_vectorised,
    _stats,
    _stats_vectorised,
)

_SORTED_LABELS = sorted(LABELS)


def _reference_normalize_rows(rows):
    normalized = []
    for row in rows:
        target = []
        for value in row:
            if isinstance(value, bool):
                raise PhotoIdentitySchpDetailError("SCHP segmentation contains boolean label")
            try:
                label = int(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PhotoIdentitySchpDetailError("SCHP segmentation contains non-integer label") from exc
            if label not in LABELS:
                raise PhotoIdentitySchpDetailError(f"SCHP segmentation contains unknown label {label}")
            target.append(label)
        normalized.append(target)
    return normalized


def _reference_stats(segmentation):
    counts = {}
    boxes = {}
    for y, row in enumerate(segmentation):
        for x, label in enumerate(row):
            counts[label] = counts.get(label, 0) + 1
            box = boxes.get(label)
            if box is None:
                boxes[label] = (x, y, x, y)
            else:
                boxes[label] = (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y))
    return counts, boxes


def _random_map(rng: random.Random, *, labels, size: int = 512):
    # Blocky regions so that boxes span real extents, plus salt noise so
    # first-occurrence order is not trivially the label order.
    grid = np.zeros((size, size), dtype=np.int64)
    for _ in range(rng.randrange(3, 12)):
        label = rng.choice(labels)
        x0, y0 = rng.randrange(0, size), rng.randrange(0, size)
        x1, y1 = rng.randrange(x0, size + 1), rng.randrange(y0, size + 1)
        grid[y0:y1, x0:x1] = label
    for _ in range(rng.randrange(0, 40)):
        grid[rng.randrange(0, size), rng.randrange(0, size)] = rng.choice(labels)
    return grid.tolist()


def _outcome(function, *args):
    try:
        return ("ok", function(*args))
    except PhotoIdentitySchpDetailError as exc:
        return ("error", str(exc))


def test_normalize_map_matches_loop_on_random_valid_maps() -> None:
    rng = random.Random(512)
    for _ in range(8):
        rows = _random_map(rng, labels=_SORTED_LABELS)
        expected = _reference_normalize_rows(rows)
        normalized, width, height = _normalize_map(rows)
        assert (width, height) == (512, 512)
        assert normalized == expected
        assert all(type(value) is int for row in normalized for value in row)
        assert _normalize_rows_vectorised(rows) == expected


def test_normalize_map_reports_first_unknown_label_in_row_major_order() -> None:
    rng = random.Random(9)
    rows = _random_map(rng, labels=_SORTED_LABELS)
    unknown = max(LABELS) + 1
    rows[300][7] = unknown + 5
    rows[12][500] = unknown  # earlier in row-major order than (300, 7)
    rows[12][40] = -1  # earlier still in the same row
    assert _outcome(_normalize_map, rows) == _outcome(_reference_normalize_rows, rows)
    assert _outcome(_normalize_map, rows) == ("error", "SCHP segmentation contains unknown label -1")


def test_normalize_map_leaves_non_int_pixels_to_the_loop() -> None:
    rng = random.Random(3)
    base = _random_map(rng, labels=_SORTED_LABELS)
    for poison, message in (
        (True, "SCHP segmentation contains boolean label"),
        ("x", "SCHP segmentation contains non-integer label"),
        (None, "SCHP segmentation contains non-integer label"),
        (float("nan"), "SCHP segmentation contains non-integer label"),
        (1 << 70, f"SCHP segmentation contains unknown label {1 << 70}"),
    ):
        rows = [list(row) for row in base]
        rows[511][511] = poison
        if type(poison) is not int:
            assert _normalize_rows_vectorised(rows) is None
        assert _outcome(_normalize_map, rows) == ("error", message)
        assert _outcome(_normalize_map, rows) == _outcome(_reference_normalize_rows, rows)
    # A float that happens to be integral is accepted by int() in the loop and
    # must therefore still be accepted overall -- through the loop path.
    rows = [list(row) for row in base]
    rows[0][0] = float(_SORTED_LABELS[-1])
    assert _normalize_rows_vectorised(rows) is None
    assert _normalize_map(rows)[0] == _reference_normalize_rows(rows)


def test_stats_match_loop_including_dict_insertion_order() -> None:
    rng = random.Random(77)
    for _ in range(8):
        rows = _random_map(rng, labels=_SORTED_LABELS)
        expected_counts, expected_boxes = _reference_stats(rows)
        counts, boxes = _stats(rows)
        assert counts == expected_counts
        assert boxes == expected_boxes
        assert list(counts) == list(expected_counts)
        assert list(boxes) == list(expected_boxes)
        assert sum(counts.values()) == 512 * 512
        vectorised = _stats_vectorised(rows)
        assert vectorised is not None
        assert vectorised == (expected_counts, expected_boxes)
        assert all(type(key) is int for key in counts)
        assert all(type(value) is int for box in boxes.values() for value in box)


def test_stats_single_label_and_single_pixel_boxes() -> None:
    rows = [[11] * 512 for _ in range(512)]
    rows[511][0] = 2
    assert _stats(rows) == _reference_stats(rows) == ({11: 512 * 512 - 1, 2: 1}, {11: (0, 0, 511, 511), 2: (0, 511, 0, 511)})


def test_stats_vectorised_declines_irregular_input() -> None:
    assert _stats_vectorised([[1, 2], [3]]) is None
    assert _stats_vectorised([]) is None
    assert _stats_vectorised([[1.0, 2.0]]) is None
    assert _stats_vectorised([[True, False]]) is None
    # ...and the public function still answers through the loop.
    assert _stats([[1, 2], [3]]) == _reference_stats([[1, 2], [3]])


def test_vectorised_paths_without_numpy_fall_back_to_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy disabled for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    rows = [[_SORTED_LABELS[(x + y) % len(_SORTED_LABELS)] for x in range(512)] for y in range(512)]
    assert _normalize_rows_vectorised(rows) is None
    assert _stats_vectorised(rows) is None
    assert _normalize_map(rows)[0] == rows
    assert _stats(rows) == _reference_stats(rows)
