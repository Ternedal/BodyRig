from __future__ import annotations

import struct
import zlib

import pytest

from bodyrig.photoreal_mesh_projection import (
    PhotorealMeshProjectionError,
    parse_mesh_projection_payload,
)


class _BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def put(self, value: int, width: int) -> None:
        assert 0 <= value < (1 << width)
        self.bits.extend((value >> (width - 1 - index)) & 1 for index in range(width))

    def align(self) -> None:
        while len(self.bits) % 8:
            self.bits.append(0)

    def bytes(self) -> bytes:
        self.align()
        return bytes(
            sum(self.bits[offset + bit] << (7 - bit) for bit in range(8))
            for offset in range(0, len(self.bits), 8)
        )


def _zigzag(value: int) -> int:
    return value * 2 if value >= 0 else -value * 2 - 1


def _mesh_box(*, reserved_coordinate_bit: int = 0, index_type: int = 0, bad_vertex_delta: bool = False) -> bytes:
    coordinates = [-1.0, 0.0, 1.0]
    vertices = [
        [1, 1, 0, 1, 1],
        [2, 1, 0, 2, 1],
        [1, 2, 0, 1, 2],
    ]
    writer = _BitWriter()
    writer.put(reserved_coordinate_bit, 1)
    writer.put(len(coordinates), 31)
    for coordinate in coordinates:
        for byte in struct.pack(">f", coordinate):
            writer.put(byte, 8)
    writer.put(0, 1)
    writer.put(len(vertices), 31)
    coordinate_bits = (len(coordinates) * 2 - 1).bit_length()
    previous = [0, 0, 0, 0, 0]
    for vertex_index, vertex in enumerate(vertices):
        for component, coordinate_index in enumerate(vertex):
            delta = coordinate_index - previous[component]
            if bad_vertex_delta and vertex_index == 0 and component == 0:
                delta = 3
            previous[component] += delta
            writer.put(_zigzag(delta), coordinate_bits)
    writer.align()
    writer.put(0, 1)
    writer.put(1, 31)
    writer.put(0, 8)
    writer.put(index_type, 8)
    indices = [0, 1, 2]
    writer.put(0, 1)
    writer.put(len(indices), 31)
    vertex_bits = (len(vertices) * 2 - 1).bit_length()
    previous_index = 0
    for index in indices:
        delta = index - previous_index
        previous_index = index
        writer.put(_zigzag(delta), vertex_bits)
    payload = writer.bytes()
    return (len(payload) + 8).to_bytes(4, "big") + b"mesh" + payload


def _deflate(raw: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    return compressor.compress(raw) + compressor.flush()


def test_parses_raw_mesh_geometry_exactly() -> None:
    result = parse_mesh_projection_payload(_mesh_box(), encoding="raw ", materialize=True)
    assert result["mesh_count"] == 1
    assert result["total_vertex_count"] == 3
    assert result["total_index_count"] == 3
    assert result["texture_ids"] == [0]
    assert result["index_types"] == [0]
    assert result["render_authority"] is False
    assert result["production_activation"] is False
    mesh = result["meshes"][0]
    assert mesh["vertices"] == [
        (0.0, 0.0, -1.0, 0.0, 0.0),
        (1.0, 0.0, -1.0, 1.0, 0.0),
        (0.0, 1.0, -1.0, 0.0, 1.0),
    ]
    assert mesh["vertex_lists"] == [{"texture_id": 0, "index_type": 0, "indices": [0, 1, 2]}]


def test_parses_raw_deflate_without_materializing_vertices() -> None:
    raw = _mesh_box()
    result = parse_mesh_projection_payload(_deflate(raw), encoding="dfl8")
    assert result["encoding"] == "dfl8"
    assert result["mesh_count"] == 1
    assert result["materialized"] is False
    assert result["meshes"][0]["vertices"] is None
    assert result["meshes"][0]["vertex_lists"] is None


def test_ignores_unknown_extension_boxes_but_records_them() -> None:
    extension = (12).to_bytes(4, "big") + b"test" + b"ABCD"
    result = parse_mesh_projection_payload(_mesh_box() + extension, encoding="raw ")
    assert result["mesh_count"] == 1
    assert result["unknown_box_types"] == ["test"]


def test_rejects_nonzero_reserved_bit() -> None:
    with pytest.raises(PhotorealMeshProjectionError, match="reserved bit"):
        parse_mesh_projection_payload(_mesh_box(reserved_coordinate_bit=1), encoding="raw ")


def test_rejects_coordinate_delta_that_leaves_table() -> None:
    with pytest.raises(PhotorealMeshProjectionError, match="coordinate index is out of range"):
        parse_mesh_projection_payload(_mesh_box(bad_vertex_delta=True), encoding="raw ")


def test_rejects_unknown_triangle_index_type() -> None:
    with pytest.raises(PhotorealMeshProjectionError, match="unsupported index_type"):
        parse_mesh_projection_payload(_mesh_box(index_type=3), encoding="raw ")


def test_rejects_more_than_two_mesh_boxes() -> None:
    raw = _mesh_box() * 3
    with pytest.raises(PhotorealMeshProjectionError, match="more than 2"):
        parse_mesh_projection_payload(raw, encoding="raw ")


def test_rejects_truncated_raw_deflate_stream() -> None:
    compressed = _deflate(_mesh_box())
    with pytest.raises(PhotorealMeshProjectionError, match="truncated|invalid"):
        parse_mesh_projection_payload(compressed[:-1], encoding="dfl8")
