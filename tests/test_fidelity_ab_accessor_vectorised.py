"""Oracle tests: the single-pass accessor reader equals the per-row reader.

`_accessor_layout` proves the bufferView bounds once instead of per row, and
`_decode_unsigned_scalars` unpacks index accessors through numpy. Both must
return exactly what the original per-row loop returned -- the same row bytes
in the same order, the same Python ints, and the same error at the same
point. The original loop is kept here as the oracle.
"""

from __future__ import annotations

import random
import struct

import numpy as np
import pytest

from bodyrig import fidelity_ab
from bodyrig.fidelity_ab import (
    FidelityAbError,
    _accessor_layout,
    _accessor_rows,
    _COMPONENT_SIZE,
    _decode_unsigned_scalars,
    _indices,
    _INDEX_FORMAT,
    _TYPE_COMPONENTS,
)


def _reference_accessor_rows(document, binary, index):
    """The pre-vectorisation per-row reader, verbatim in behaviour."""
    accessors = document["accessors"]
    accessor = accessors[index]
    view = document["bufferViews"][accessor["bufferView"]]
    component_type = accessor["componentType"]
    accessor_type = accessor["type"]
    count = accessor["count"]
    element_size = _COMPONENT_SIZE[component_type] * _TYPE_COMPONENTS[accessor_type]
    stride = view.get("byteStride", element_size)
    view_offset = view.get("byteOffset", 0)
    accessor_offset = accessor.get("byteOffset", 0)
    view_length = view["byteLength"]
    start = view_offset + accessor_offset
    rows: list[bytes] = []
    for item in range(count):
        row_start = start + item * stride
        row_end = row_start + element_size
        if row_end > view_offset + view_length or row_end > len(binary):
            raise FidelityAbError("glTF accessor exceeds its bufferView")
        rows.append(binary[row_start:row_end])
    descriptor = {
        "componentType": component_type,
        "type": accessor_type,
        "normalized": bool(accessor.get("normalized", False)),
    }
    return descriptor, rows


def _document(*, component_type, accessor_type, count, stride, view_offset, accessor_offset, view_length, normalized=None):
    accessor = {
        "bufferView": 0,
        "componentType": component_type,
        "type": accessor_type,
        "count": count,
        "byteOffset": accessor_offset,
    }
    if normalized is not None:
        accessor["normalized"] = normalized
    view = {"buffer": 0, "byteOffset": view_offset, "byteLength": view_length}
    if stride is not None:
        view["byteStride"] = stride
    return {"accessors": [accessor], "bufferViews": [view]}


def _outcome(function, *args):
    try:
        return ("ok", function(*args))
    except FidelityAbError as exc:
        return ("error", str(exc))


def test_accessor_rows_match_reference_on_random_layouts() -> None:
    rng = random.Random(20261106)
    binary = bytes(rng.getrandbits(8) for _ in range(4096))
    checked_ok = 0
    checked_error = 0
    for _ in range(600):
        component_type = rng.choice(sorted(_COMPONENT_SIZE))
        accessor_type = rng.choice(sorted(_TYPE_COMPONENTS))
        if accessor_type.startswith("MAT") and _COMPONENT_SIZE[component_type] < 4:
            continue
        element_size = _COMPONENT_SIZE[component_type] * _TYPE_COMPONENTS[accessor_type]
        stride = rng.choice([None, element_size, element_size + rng.randrange(0, 9), element_size * 2])
        count = rng.choice([0, 1, 2, 3, rng.randrange(0, 64)])
        view_offset = rng.randrange(0, 128)
        accessor_offset = rng.randrange(0, 64)
        effective_stride = element_size if stride is None else stride
        # Mix exact fits, generous views and views one byte too short.
        exact = accessor_offset + max(0, count - 1) * effective_stride + element_size if count else accessor_offset
        view_length = rng.choice([exact, exact - 1, exact + rng.randrange(0, 32), len(binary) + 64, 0])
        if view_length < 0:
            view_length = 0
        document = _document(
            component_type=component_type,
            accessor_type=accessor_type,
            count=count,
            stride=stride,
            view_offset=view_offset,
            accessor_offset=accessor_offset,
            view_length=view_length,
            normalized=rng.choice([None, True, False]),
        )
        expected = _outcome(_reference_accessor_rows, document, binary, 0)
        actual = _outcome(_accessor_rows, document, binary, 0)
        assert actual == expected
        if expected[0] == "ok":
            checked_ok += 1
            descriptor, rows = expected[1]
            layout_descriptor, start, layout_stride, layout_element, layout_count = _accessor_layout(document, binary, 0)
            assert layout_descriptor == descriptor
            assert (layout_stride, layout_element, layout_count) == (effective_stride, element_size, count)
            assert start == view_offset + accessor_offset
            assert len(rows) == count
        else:
            checked_error += 1
    assert checked_ok > 150
    assert checked_error > 50


def test_accessor_bounds_check_is_exact_at_both_edges() -> None:
    binary = bytes(range(256))
    # 5 x VEC3 float32 = 60 bytes with stride 16 -> last row ends at 4*16+12 = 76.
    for view_length, outcome in ((76, "ok"), (75, "error")):
        document = _document(
            component_type=5126,
            accessor_type="VEC3",
            count=5,
            stride=16,
            view_offset=0,
            accessor_offset=0,
            view_length=view_length,
        )
        assert _outcome(_accessor_rows, document, binary, 0)[0] == outcome
        assert _outcome(_reference_accessor_rows, document, binary, 0)[0] == outcome
    # A view that is long enough but a GLB binary that is not.
    document = _document(component_type=5126, accessor_type="VEC3", count=5, stride=16, view_offset=200, accessor_offset=0, view_length=400)
    assert _outcome(_accessor_rows, document, binary, 0) == ("error", "glTF accessor exceeds its bufferView")
    # count == 0 never touches bytes, exactly like the empty loop.
    document = _document(component_type=5126, accessor_type="VEC3", count=0, stride=16, view_offset=5000, accessor_offset=0, view_length=0)
    assert _accessor_rows(document, binary, 0)[1] == []


@pytest.mark.parametrize("component_type", sorted(_INDEX_FORMAT))
@pytest.mark.parametrize("padding", [0, 1, 3, 5])
def test_decode_unsigned_scalars_matches_struct_loop(component_type: int, padding: int) -> None:
    rng = random.Random(component_type * 100 + padding)
    fmt = _INDEX_FORMAT[component_type]
    element_size = struct.calcsize(fmt)
    stride = element_size + padding
    count = 257
    limit = 1 << (8 * element_size)
    expected = [rng.randrange(0, limit) for _ in range(count)]
    prefix = bytes(rng.getrandbits(8) for _ in range(7))
    body = bytearray()
    for value in expected:
        body += struct.pack(fmt, value) + bytes(rng.getrandbits(8) for _ in range(padding))
    binary = prefix + bytes(body) + b"\xff" * 9
    decoded = _decode_unsigned_scalars(binary, start=len(prefix), stride=stride, element_size=element_size, count=count, fmt=fmt)
    assert decoded == expected
    assert all(type(value) is int for value in decoded)
    assert _decode_unsigned_scalars(binary, start=len(prefix), stride=stride, element_size=element_size, count=0, fmt=fmt) == []


def test_indices_match_reference_decoding_and_range_check() -> None:
    rng = random.Random(7)
    vertex_count = 1000
    for component_type in sorted(_INDEX_FORMAT):
        fmt = _INDEX_FORMAT[component_type]
        element_size = struct.calcsize(fmt)
        values = [rng.randrange(0, min(vertex_count, 1 << (8 * element_size))) for _ in range(3 * 400)]
        binary = b"".join(struct.pack(fmt, value) for value in values)
        document = _document(
            component_type=component_type,
            accessor_type="SCALAR",
            count=len(values),
            stride=None,
            view_offset=0,
            accessor_offset=0,
            view_length=len(binary),
        )
        primitive = {"indices": 0}
        assert _indices(document, binary, primitive, vertex_count) == values
        # One index exactly at vertex_count is rejected; vertex_count - 1 is accepted.
        edge = values[:]
        edge[123] = min(vertex_count - 1, (1 << (8 * element_size)) - 1)
        edge_binary = b"".join(struct.pack(fmt, value) for value in edge)
        assert _indices(document, edge_binary, primitive, vertex_count) == edge
        if vertex_count < 1 << (8 * element_size):
            bad = values[:]
            bad[123] = vertex_count
            bad_binary = b"".join(struct.pack(fmt, value) for value in bad)
            with pytest.raises(FidelityAbError, match="triangle index exceeds POSITION accessor"):
                _indices(document, bad_binary, primitive, vertex_count)
    # Non-scalar or signed component accessors are still rejected before decoding.
    document = _document(component_type=5122, accessor_type="SCALAR", count=3, stride=None, view_offset=0, accessor_offset=0, view_length=6)
    with pytest.raises(FidelityAbError, match="unsigned scalar accessor"):
        _indices(document, b"\x00" * 6, {"indices": 0}, 10)
    # An accessor that escapes its view is rejected with the layout error, not decoded.
    document = _document(component_type=5123, accessor_type="SCALAR", count=4, stride=None, view_offset=0, accessor_offset=0, view_length=7)
    with pytest.raises(FidelityAbError, match="exceeds its bufferView"):
        _indices(document, b"\x00" * 8, {"indices": 0}, 10)


def test_decode_without_numpy_uses_struct_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy disabled for this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    binary = struct.pack("<HHHH", 1, 65535, 7, 0)
    assert _decode_unsigned_scalars(binary, start=0, stride=2, element_size=2, count=4, fmt="<H") == [1, 65535, 7, 0]
    assert _decode_unsigned_scalars(binary, start=0, stride=4, element_size=2, count=2, fmt="<H") == [1, 7]


def test_numpy_decode_reads_exactly_the_row_bytes() -> None:
    # Overlapping-free layout with trailing garbage inside the view: the numpy
    # path must not read past the last element nor pick up the padding bytes.
    binary = np.asarray([5, 0, 9, 9, 6, 0, 9, 9, 7, 0], dtype=np.uint8).tobytes()
    assert _decode_unsigned_scalars(binary, start=0, stride=4, element_size=2, count=3, fmt="<H") == [5, 6, 7]
    assert fidelity_ab._INDEX_FORMAT[5125] == "<I"
