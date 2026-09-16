from __future__ import annotations

import hashlib
import math
import struct
import zlib
from typing import Any

FORMAT = "bodyrig-spherical-v2-mesh-geometry"
VERSION = 1
MAX_ENCODED_BYTES = 64 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MESHES = 2
MAX_COORDINATES = 2_000_000
MAX_VERTICES_PER_MESH = 1_000_000
MAX_VERTEX_LISTS_PER_MESH = 4096
MAX_INDICES_PER_LIST = 4_000_000
MAX_TOTAL_INDICES = 8_000_000
VALID_INDEX_TYPES = {0, 1, 2}


class PhotorealMeshProjectionError(ValueError):
    pass


class _BitReader:
    def __init__(self, data: bytes) -> None:
        self._data = memoryview(data)
        self._bit = 0

    @property
    def remaining_bits(self) -> int:
        return len(self._data) * 8 - self._bit

    @property
    def byte_aligned(self) -> bool:
        return self._bit % 8 == 0

    def read(self, width: int, *, label: str) -> int:
        if isinstance(width, bool) or width < 0:
            raise PhotorealMeshProjectionError(f"{label} width is invalid")
        if width == 0:
            return 0
        if width > self.remaining_bits:
            raise PhotorealMeshProjectionError(f"{label} is truncated")
        value = 0
        while width:
            byte_index = self._bit // 8
            bit_offset = self._bit % 8
            available = 8 - bit_offset
            take = min(width, available)
            shift = available - take
            mask = (1 << take) - 1
            value = (value << take) | ((self._data[byte_index] >> shift) & mask)
            self._bit += take
            width -= take
        return value

    def read_bytes(self, count: int, *, label: str) -> bytes:
        if not self.byte_aligned:
            raise PhotorealMeshProjectionError(f"{label} is not byte-aligned")
        if isinstance(count, bool) or count < 0 or count * 8 > self.remaining_bits:
            raise PhotorealMeshProjectionError(f"{label} is truncated")
        start = self._bit // 8
        self._bit += count * 8
        return bytes(self._data[start : start + count])

    def read_reserved31(self, *, label: str) -> int:
        if self.read(1, label=f"{label} reserved bit") != 0:
            raise PhotorealMeshProjectionError(f"{label} reserved bit is non-zero")
        return self.read(31, label=label)

    def align_byte(self) -> None:
        remainder = self._bit % 8
        if remainder:
            self._bit += 8 - remainder
            if self._bit > len(self._data) * 8:
                raise PhotorealMeshProjectionError("mesh padding is truncated")


def _bit_width(count: int, *, label: str) -> int:
    if isinstance(count, bool) or count < 1:
        raise PhotorealMeshProjectionError(f"{label} must be positive")
    return (count * 2 - 1).bit_length()


def _zigzag(value: int) -> int:
    return -(value // 2) - 1 if value & 1 else value // 2


def _decode_payload(encoded: bytes, encoding: str) -> bytes:
    if not isinstance(encoded, (bytes, bytearray, memoryview)):
        raise PhotorealMeshProjectionError("mesh projection payload must be bytes")
    raw = bytes(encoded)
    if not raw:
        raise PhotorealMeshProjectionError("mesh projection payload is empty")
    if len(raw) > MAX_ENCODED_BYTES:
        raise PhotorealMeshProjectionError(
            f"mesh projection payload exceeds encoded safety bound {MAX_ENCODED_BYTES}"
        )
    if encoding == "raw ":
        if len(raw) > MAX_DECOMPRESSED_BYTES:
            raise PhotorealMeshProjectionError(
                f"mesh projection payload exceeds decompressed safety bound {MAX_DECOMPRESSED_BYTES}"
            )
        return raw
    if encoding != "dfl8":
        raise PhotorealMeshProjectionError(f"unsupported mesh projection encoding: {encoding!r}")
    decoder = zlib.decompressobj(wbits=-15)
    try:
        decoded = decoder.decompress(raw, MAX_DECOMPRESSED_BYTES + 1)
    except zlib.error as exc:
        raise PhotorealMeshProjectionError("mesh projection raw-deflate payload is invalid") from exc
    if len(decoded) > MAX_DECOMPRESSED_BYTES or decoder.unconsumed_tail:
        raise PhotorealMeshProjectionError(
            f"mesh projection payload exceeds decompressed safety bound {MAX_DECOMPRESSED_BYTES}"
        )
    if not decoder.eof:
        raise PhotorealMeshProjectionError("mesh projection raw-deflate payload is truncated")
    if decoder.unused_data:
        raise PhotorealMeshProjectionError("mesh projection raw-deflate payload has trailing compressed data")
    decoded += decoder.flush()
    if len(decoded) > MAX_DECOMPRESSED_BYTES:
        raise PhotorealMeshProjectionError(
            f"mesh projection payload exceeds decompressed safety bound {MAX_DECOMPRESSED_BYTES}"
        )
    return decoded


def _iter_boxes(data: bytes):
    offset = 0
    count = 0
    end = len(data)
    while offset < end:
        if end - offset < 8:
            if data[offset:] == b"\x00" * (end - offset):
                break
            raise PhotorealMeshProjectionError("decompressed mesh container has trailing bytes")
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8].decode("latin-1")
        header = 8
        if size == 1:
            if end - offset < 16:
                raise PhotorealMeshProjectionError("decompressed mesh extended box header is truncated")
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            raise PhotorealMeshProjectionError(
                f"decompressed mesh box {box_type!r} has invalid bounds"
            )
        yield box_type, data[offset + header : offset + size]
        offset += size
        count += 1
        if count > 100_000:
            raise PhotorealMeshProjectionError("decompressed mesh box safety bound exceeded")


def _parse_mesh(data: bytes, *, materialize: bool) -> dict[str, Any]:
    reader = _BitReader(data)
    coordinate_count = reader.read_reserved31(label="mesh coordinate_count")
    if not 1 <= coordinate_count <= MAX_COORDINATES:
        raise PhotorealMeshProjectionError(
            f"mesh coordinate_count must be in 1..{MAX_COORDINATES}"
        )
    coordinate_bytes = reader.read_bytes(coordinate_count * 4, label="mesh coordinates")
    coordinates = [item[0] for item in struct.iter_unpack(">f", coordinate_bytes)]
    if len(coordinates) != coordinate_count or any(not math.isfinite(value) for value in coordinates):
        raise PhotorealMeshProjectionError("mesh coordinate table contains non-finite values")

    vertex_count = reader.read_reserved31(label="mesh vertex_count")
    if not 1 <= vertex_count <= MAX_VERTICES_PER_MESH:
        raise PhotorealMeshProjectionError(
            f"mesh vertex_count must be in 1..{MAX_VERTICES_PER_MESH}"
        )
    coordinate_bits = _bit_width(coordinate_count, label="mesh coordinate_count")
    previous = [0, 0, 0, 0, 0]
    vertices: list[tuple[float, float, float, float, float]] | None = [] if materialize else None
    for vertex_index in range(vertex_count):
        resolved: list[int] = []
        for component in range(5):
            delta = _zigzag(
                reader.read(
                    coordinate_bits,
                    label=f"mesh vertex {vertex_index} coordinate delta {component}",
                )
            )
            previous[component] += delta
            index = previous[component]
            if not 0 <= index < coordinate_count:
                raise PhotorealMeshProjectionError(
                    f"mesh vertex {vertex_index} coordinate index is out of range"
                )
            resolved.append(index)
        if vertices is not None:
            vertices.append(tuple(float(coordinates[index]) for index in resolved))  # type: ignore[arg-type]
    reader.align_byte()

    list_count = reader.read_reserved31(label="mesh vertex_list_count")
    if not 1 <= list_count <= MAX_VERTEX_LISTS_PER_MESH:
        raise PhotorealMeshProjectionError(
            f"mesh vertex_list_count must be in 1..{MAX_VERTEX_LISTS_PER_MESH}"
        )
    vertex_bits = _bit_width(vertex_count, label="mesh vertex_count")
    vertex_lists: list[dict[str, Any]] | None = [] if materialize else None
    texture_ids: set[int] = set()
    index_types: set[int] = set()
    total_indices = 0
    for list_index in range(list_count):
        texture_id = reader.read(8, label=f"mesh vertex list {list_index} texture_id")
        index_type = reader.read(8, label=f"mesh vertex list {list_index} index_type")
        if index_type not in VALID_INDEX_TYPES:
            raise PhotorealMeshProjectionError(
                f"mesh vertex list {list_index} uses unsupported index_type {index_type}"
            )
        index_count = reader.read_reserved31(label=f"mesh vertex list {list_index} index_count")
        if not 1 <= index_count <= MAX_INDICES_PER_LIST:
            raise PhotorealMeshProjectionError(
                f"mesh index_count must be in 1..{MAX_INDICES_PER_LIST}"
            )
        total_indices += index_count
        if total_indices > MAX_TOTAL_INDICES:
            raise PhotorealMeshProjectionError(
                f"mesh total index count exceeds safety bound {MAX_TOTAL_INDICES}"
            )
        previous_index = 0
        indices: list[int] | None = [] if materialize else None
        for item_index in range(index_count):
            previous_index += _zigzag(
                reader.read(
                    vertex_bits,
                    label=f"mesh vertex list {list_index} index delta {item_index}",
                )
            )
            if not 0 <= previous_index < vertex_count:
                raise PhotorealMeshProjectionError(
                    f"mesh vertex list {list_index} index is out of range"
                )
            if indices is not None:
                indices.append(previous_index)
        reader.align_byte()
        texture_ids.add(texture_id)
        index_types.add(index_type)
        if vertex_lists is not None:
            vertex_lists.append(
                {
                    "texture_id": texture_id,
                    "index_type": index_type,
                    "indices": indices,
                }
            )

    return {
        "coordinate_count": coordinate_count,
        "vertex_count": vertex_count,
        "vertex_list_count": list_count,
        "index_count": total_indices,
        "texture_ids": sorted(texture_ids),
        "index_types": sorted(index_types),
        "vertices": vertices,
        "vertex_lists": vertex_lists,
        "trailing_extension_bytes": reader.remaining_bits // 8,
    }


def parse_mesh_projection_payload(
    encoded_payload: bytes,
    *,
    encoding: str,
    materialize: bool = False,
) -> dict[str, Any]:
    decoded = _decode_payload(encoded_payload, encoding)
    meshes: list[dict[str, Any]] = []
    unknown_box_types: set[str] = set()
    for box_type, payload in _iter_boxes(decoded):
        if box_type == "mesh":
            if len(meshes) >= MAX_MESHES:
                raise PhotorealMeshProjectionError(
                    f"mesh projection contains more than {MAX_MESHES} mesh boxes"
                )
            meshes.append(_parse_mesh(payload, materialize=materialize))
        else:
            unknown_box_types.add(box_type)
    if not meshes:
        raise PhotorealMeshProjectionError("mesh projection contains no mesh box")
    total_vertices = sum(int(mesh["vertex_count"]) for mesh in meshes)
    total_indices = sum(int(mesh["index_count"]) for mesh in meshes)
    return {
        "format": FORMAT,
        "version": VERSION,
        "encoding": encoding,
        "encoded_payload_bytes": len(encoded_payload),
        "decompressed_payload_bytes": len(decoded),
        "decompressed_payload_sha256": hashlib.sha256(decoded).hexdigest(),
        "mesh_count": len(meshes),
        "total_vertex_count": total_vertices,
        "total_index_count": total_indices,
        "texture_ids": sorted(
            {int(texture_id) for mesh in meshes for texture_id in mesh["texture_ids"]}
        ),
        "index_types": sorted(
            {int(index_type) for mesh in meshes for index_type in mesh["index_types"]}
        ),
        "unknown_box_types": sorted(unknown_box_types),
        "meshes": meshes,
        "materialized": materialize,
        "render_authority": False,
        "production_activation": False,
    }
