from __future__ import annotations

import json

from bodyrig.photoreal_stash_inventory_cli import _projection_diagnostics, _tag_hints


def test_projection_diagnostics_are_path_private_and_non_authoritative() -> None:
    inventory = {
        "videos": [
            {
                "path": "E:/private/flat.mp4",
                "projection": "flat",
                "stereo_layout": "mono",
                "tags": [],
            },
            {
                "path": "E:/private/vr180.mp4",
                "projection": "vr180",
                "stereo_layout": "side-by-side",
                "tags": ["VR180", "SBS", "Fish-Eye"],
            },
            {
                "path": "E:/private/vr360.mp4",
                "projection": "vr360",
                "stereo_layout": "over-under",
                "tags": ["VR360", "Equirectangular", "Spherical Video"],
            },
            {
                "path": "E:/private/ambiguous.mp4",
                "projection": "projection-ambiguous-2to1",
                "stereo_layout": "unknown",
                "tags": [],
            },
        ]
    }

    result = _projection_diagnostics(inventory)

    assert result["diagnostic_only"] is True
    assert result["authority"] is False
    assert result["production_activation"] is False
    assert result["container_projection_metadata_probe_required"] is True
    assert result["spatial_source_count"] == 3
    assert result["projection_counts"] == {
        "flat": 1,
        "projection-ambiguous-2to1": 1,
        "vr180": 1,
        "vr360": 1,
    }
    assert result["stereo_layout_counts"] == {
        "mono": 1,
        "over-under": 1,
        "side-by-side": 1,
        "unknown": 1,
    }
    assert result["spatial_projection_tag_hint_counts"] == {
        "equirectangular": 1,
        "fisheye": 1,
        "mesh-or-spherical": 1,
    }
    encoded = json.dumps(result, sort_keys=True)
    assert "E:/private" not in encoded
    assert "path" not in encoded


def test_projection_tag_hints_normalize_common_spellings() -> None:
    assert _tag_hints(["Fish-Eye", "Spherical_Video", "Panoramic"]) == {
        "fisheye",
        "mesh-or-spherical",
        "equirectangular",
    }
