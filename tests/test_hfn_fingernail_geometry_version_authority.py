from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import hands_feet_nails_fingernail_geometry_candidate as geometry


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


def _bind_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> tuple[Path, Path]:
    package_path = tmp_path / "candidate.mrbody"
    receipt_path = tmp_path / "candidate.json"
    package_path.write_bytes(b"fingernail-geometry-package")

    avatar = b"fingernail-geometry-avatar"
    basecolor = b"source-grounded-basecolor"
    source_detail_package_sha = "1" * 64
    counts = {f"nail-{index}": 1 for index in range(10)}
    receipt = {
        "format": geometry.FORMAT,
        "version": version,
        "policy_revision": geometry.POLICY_REVISION,
        "candidate_id": "candidate-test",
        "person_id": "person-" + "2" * 32,
        "body_revision": "body-r0001",
        "capture_id": "capture-test",
        "body_id": "body-test",
        "bodyrig_revision": "a" * 40,
        "source_detail_receipt_sha256": "0" * 64,
        "source_detail_package_sha256": source_detail_package_sha,
        "geometry_package_sha256": geometry._sha256_file(package_path),
        "source_avatar_sha256": "3" * 64,
        "geometry_avatar_sha256": geometry._sha256_bytes(avatar),
        "uv_evidence_sha256": "4" * 64,
        "uv_evidence_path_sha256": "5" * 64,
        "active_basecolor_sha256": geometry._sha256_bytes(basecolor),
        "node_name": geometry.NODE_NAME,
        "mesh_name": geometry.MESH_NAME,
        "material_name": geometry.MATERIAL_NAME,
        "plate_count": 10,
        "triangle_count": 10,
        "vertex_count": 30,
        "plate_triangle_counts": counts,
        "offset_meters": geometry.OFFSET_METERS,
        "skin_index": 0,
        "source_grounded": True,
        "additive_geometry_only": True,
        "geometry_modified": True,
        "texture_modified": False,
        "human_review_required": True,
        "production_activation": False,
    }
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    document = {
        "nodes": [{"name": geometry.NODE_NAME}],
        "meshes": [{"name": geometry.MESH_NAME}],
        "materials": [{"name": geometry.MATERIAL_NAME}],
        "extras": {
            "bodyrig": {
                "handsFeetNailsFingernailGeometry": {
                    "sourceDetailPackageSha256": source_detail_package_sha,
                }
            }
        },
    }
    monkeypatch.setattr(
        geometry,
        "geometry_paths",
        lambda *_args, **_kwargs: (package_path, receipt_path),
    )
    monkeypatch.setattr(geometry, "_package_avatar", lambda _path: (avatar, "body-test"))
    monkeypatch.setattr(geometry, "_read_glb", lambda _avatar: (document, b"binary"))
    monkeypatch.setattr(
        geometry,
        "_active_basecolor",
        lambda *_args, **_kwargs: (basecolor, None, None, None, None),
    )
    return package_path, receipt_path


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_fingernail_geometry_readback_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    _bind_candidate(monkeypatch, tmp_path, version)

    with pytest.raises(
        geometry.HandsFeetNailsFingernailGeometryError,
        match="HFN fingernail geometry receipt format/version/policy mismatch",
    ):
        geometry.read_fingernail_geometry_candidate(
            tmp_path,
            "person-" + "2" * 32,
            body_revision="body-r0001",
            capture_id="capture-test",
            candidate_id="candidate-test",
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_fingernail_geometry_readback_preserves_numeric_v1_and_hfn_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    package_path, receipt_path = _bind_candidate(monkeypatch, tmp_path, version)

    value = geometry.read_fingernail_geometry_candidate(
        tmp_path,
        "person-" + "2" * 32,
        body_revision="body-r0001",
        capture_id="capture-test",
        candidate_id="candidate-test",
    )

    assert value["version"] == version
    assert value["plate_count"] == 10
    assert value["skin_index"] == 0
    assert value["source_grounded"] is True
    assert value["additive_geometry_only"] is True
    assert value["geometry_modified"] is True
    assert value["texture_modified"] is False
    assert value["human_review_required"] is True
    assert value["production_activation"] is False
    assert value["package_path"] == str(package_path)
    assert value["receipt_path"] == str(receipt_path)
