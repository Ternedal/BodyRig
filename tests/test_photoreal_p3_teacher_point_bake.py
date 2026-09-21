from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import bodyrig.photoreal_p3_teacher_point_bake as bake
from bodyrig.photoreal_p3_teacher_point_bake import (
    PhotorealP3TeacherPointBakeError,
    read_exavatar_teacher_points,
)


def test_read_teacher_points_normalizes_rgb(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bake, "MIN_SMPLX_VERTEX_COUNT", 3)
    source = tmp_path / "rgb.txt"
    source.write_text(
        "0 0 0 255 0 0\n"
        "1 0 0 0 128 0\n"
        "0 1 0 0 0 255\n",
        encoding="utf-8",
    )

    xyz, rgb = read_exavatar_teacher_points(source, np=np)

    assert xyz.shape == (3, 3)
    assert rgb.shape == (3, 3)
    assert rgb[0].tolist() == pytest.approx([1.0, 0.0, 0.0])
    assert rgb[1].tolist() == pytest.approx([0.0, 128.0 / 255.0, 0.0])
    assert rgb[2].tolist() == pytest.approx([0.0, 0.0, 1.0])


def test_read_teacher_points_rejects_short_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bake, "MIN_SMPLX_VERTEX_COUNT", 3)
    source = tmp_path / "rgb.txt"
    source.write_text(
        "0 0 0 255 0 0\n"
        "1 0 0 0 255 0\n",
        encoding="utf-8",
    )

    with pytest.raises(
        PhotorealP3TeacherPointBakeError,
        match="smaller than the canonical SMPL-X surface",
    ):
        read_exavatar_teacher_points(source, np=np)


def test_read_teacher_points_rejects_rgb_outside_byte_range(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bake, "MIN_SMPLX_VERTEX_COUNT", 1)
    source = tmp_path / "rgb.txt"
    source.write_text("0 0 0 256 0 0\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP3TeacherPointBakeError,
        match="outside 0..255",
    ):
        read_exavatar_teacher_points(source, np=np)


def test_read_teacher_points_rejects_non_finite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bake, "MIN_SMPLX_VERTEX_COUNT", 1)
    source = tmp_path / "rgb.txt"
    source.write_text("nan 0 0 1 2 3\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP3TeacherPointBakeError,
        match="non-finite",
    ):
        read_exavatar_teacher_points(source, np=np)


def test_validate_teacher_arrays_requires_matching_xyz_rgb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bake, "MIN_SMPLX_VERTEX_COUNT", 2)
    xyz = np.zeros((2, 3), dtype=np.float32)
    rgb = np.zeros((3, 3), dtype=np.float32)

    with pytest.raises(
        PhotorealP3TeacherPointBakeError,
        match="invalid shape/count",
    ):
        bake._validate_teacher_arrays(
            np=np,
            teacher_xyz=xyz,
            teacher_rgb=rgb,
        )


def test_validate_teacher_arrays_rejects_non_normalized_rgb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bake, "MIN_SMPLX_VERTEX_COUNT", 2)
    xyz = np.zeros((2, 3), dtype=np.float32)
    rgb = np.asarray([[0.0, 0.0, 0.0], [1.1, 0.0, 0.0]], dtype=np.float32)

    with pytest.raises(
        PhotorealP3TeacherPointBakeError,
        match="outside normalized 0..1 range",
    ):
        bake._validate_teacher_arrays(
            np=np,
            teacher_xyz=xyz,
            teacher_rgb=rgb,
        )
