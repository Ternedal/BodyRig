from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.photoreal_source_verify as source_verify
from bodyrig.photoreal_source_verify import PhotorealSourceVerifyError, verify_inventory_sources


def _inventory(*, projection: str) -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "video_file_count": 1,
        "image_file_count": 0,
        "summary": {"source_universe_exhaustive": True},
        "videos": [
            {
                "scene_id": "s1",
                "path": "source.mp4",
                "size_bytes": 100,
                "projection": projection,
            }
        ],
        "images": [],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


@pytest.mark.parametrize("projection", sorted(source_verify.SPATIAL_HINT_PROJECTIONS))
def test_spatial_v2_preflight_rejects_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
    projection: str,
) -> None:
    calls: list[tuple[str, str]] = []

    def reject_projection(path: Path) -> dict[str, object]:
        calls.append(("preflight", str(path)))
        raise source_verify.PhotorealProjectionAuthorityError(
            "spatial source lacks Spherical V2 sv3d/proj authority"
        )

    def hash_must_not_run(path: Path) -> str:
        calls.append(("hash", str(path)))
        raise AssertionError("hashing started before projection preflight completed")

    monkeypatch.setattr(source_verify, "_probe_v2_projection", reject_projection)

    with pytest.raises(PhotorealSourceVerifyError, match="Spherical V2 preflight failed before hashing"):
        verify_inventory_sources(
            _inventory(projection=projection),
            path_mapping={},
            exists_file=lambda _path: True,
            file_size=lambda _path: 100,
            hash_file=hash_must_not_run,
        )

    assert calls == [("preflight", "source.mp4")]


def test_spatial_v2_preflight_allows_hashing_but_does_not_grant_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def accept_projection(path: Path) -> dict[str, object]:
        calls.append(("preflight", str(path)))
        return {"projection_type": "equi"}

    def hash_after_preflight(path: Path) -> str:
        calls.append(("hash", str(path)))
        return "a" * 64

    monkeypatch.setattr(source_verify, "_probe_v2_projection", accept_projection)

    result = verify_inventory_sources(
        _inventory(projection="projection-ambiguous-2to1"),
        path_mapping={},
        exists_file=lambda _path: True,
        file_size=lambda _path: 100,
        hash_file=hash_after_preflight,
    )

    assert calls == [("preflight", "source.mp4"), ("hash", "source.mp4")]
    assert result["all_sources_sha256_bound"] is True
    assert "projection_authority" not in result["sources"][0]


def test_flat_video_skips_projection_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_verify,
        "_probe_v2_projection",
        lambda _path: (_ for _ in ()).throw(AssertionError("flat source was probed")),
    )

    result = verify_inventory_sources(
        _inventory(projection="flat"),
        path_mapping={},
        exists_file=lambda _path: True,
        file_size=lambda _path: 100,
        hash_file=lambda _path: "b" * 64,
    )

    assert result["source_count"] == 1
    assert result["sources"][0]["sha256"] == "b" * 64
