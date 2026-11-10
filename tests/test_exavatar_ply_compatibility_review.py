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


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (
            "ply\\nformat ascii 1.0\\nelement vertex 1\\n"
            "property float x\\nproperty float x\\nproperty float z\\nend_header\\n",
            "lacks x/y/z|Duplicate PLY vertex",
        ),
        (
            "ply\\nformat ascii 1.0\\nelement vertex 1\\n"
            "property float x\\nproperty float y\\nproperty float z\\n"
            "property list uchar int indices\\nend_header\\n",
            "List-valued vertex properties",
        ),
        (
            "ply\\nformat ascii 1.0\\nelement vertex 250001\\n"
            "property float x\\nproperty float y\\nproperty float z\\nend_header\\n",
            "vertex count invalid",
        ),
    ],
)
def test_rejects_invalid_vertex_headers(tmp_path: Path, header: str, expected: str) -> None:
    mesh = tmp_path / "invalid.ply"
    mesh.write_bytes(header.replace("\\n", "\n").encode("ascii") + b"1 2 3\n")
    with pytest.raises(FitDiagnosticError, match=expected):
        list(_vertices(mesh))


def test_ascii_vertex_line_limit_fails_closed(tmp_path: Path) -> None:
    mesh = tmp_path / "oversized.ply"
    mesh.write_bytes(
        b"ply\nformat ascii 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n"
        + b"1 2 3 " + b" " * 65536 + b"\n"
    )
    with pytest.raises(FitDiagnosticError, match="vertex line exceeds diagnostic limits"):
        list(_vertices(mesh))


def test_symlink_mesh_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real.ply"
    target.write_bytes(
        b"ply\nformat ascii 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n1 2 3\n"
    )
    link = tmp_path / "linked.ply"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable on this host")
    with pytest.raises(FitDiagnosticError, match="Missing mesh"):
        list(_vertices(link))
