"""Synthetic, read-only PLY compatibility regression tests for ExAvatar diagnostics.

These tests do not use physical-rig data or authorize photoreal acceptance.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from bodyrig.photoreal_exavatar_fit_diagnostic import FitDiagnosticError, _vertices


@pytest.mark.parametrize("fmt", ["ascii", "binary_little_endian", "binary_big_endian"])
def test_ply_xyz_and_extra_vertex_property(tmp_path: Path, fmt: str) -> None:
    mesh = tmp_path / "fixture.ply"
    header = (
        f"ply\nformat {fmt} 1.0\nelement vertex 2\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nend_header\n"
    ).encode("ascii")
    if fmt == "ascii":
        payload = b"1 2 3 255\n-4 5 6 0\n"
    else:
        endian = "<" if fmt == "binary_little_endian" else ">"
        payload = struct.pack(endian + "fffB", 1, 2, 3, 255)
        payload += struct.pack(endian + "fffB", -4, 5, 6, 0)
    mesh.write_bytes(header + payload)
    assert list(_vertices(mesh)) == [(1.0, 2.0, 3.0), (-4.0, 5.0, 6.0)]


@pytest.mark.parametrize("fmt", ["ascii", "binary_little_endian", "binary_big_endian"])
def test_nonfinite_coordinates_are_exposed_to_projection_filter(tmp_path: Path, fmt: str) -> None:
    """Current contract: parser yields nonfinite values; projection filters them."""
    mesh = tmp_path / "nonfinite.ply"
    header = (
        f"ply\nformat {fmt} 1.0\nelement vertex 1\n"
        "property float x\nproperty float y\nproperty float z\nend_header\n"
    ).encode("ascii")
    payload = b"nan 1 2\n" if fmt == "ascii" else struct.pack(
        ("<" if fmt == "binary_little_endian" else ">") + "fff", math.nan, 1, 2
    )
    mesh.write_bytes(header + payload)
    x, y, z = next(_vertices(mesh))
    assert math.isnan(x) and y == 1 and z == 2


@pytest.mark.parametrize("fmt", ["binary_little_endian", "binary_big_endian"])
def test_truncated_binary_record_fails_closed(tmp_path: Path, fmt: str) -> None:
    mesh = tmp_path / "truncated.ply"
    mesh.write_bytes(
        (
            f"ply\nformat {fmt} 1.0\nelement vertex 1\n"
            "property float x\nproperty float y\nproperty float z\nend_header\n"
        ).encode("ascii") + b"\x00" * 11
    )
    with pytest.raises(FitDiagnosticError, match="Truncated binary PLY"):
        list(_vertices(mesh))
