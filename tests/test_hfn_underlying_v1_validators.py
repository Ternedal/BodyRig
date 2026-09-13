from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import bodyrig.hands_feet_nails_authority as authority
import bodyrig.hands_feet_nails_detail_candidate as candidate
from bodyrig.hands_feet_nails_detail_texture import (
    MAX_CHANNEL_DELTA_LEVELS,
    METHOD,
    MIN_REGION_CHANGED_PIXELS,
    MIN_REGION_MASK_PIXELS,
)
from bodyrig.hands_feet_nails_source_capture import REQUIRED_REGIONS

PERSON = "person-" + "1" * 32
BODY = "body-r0001"
CAPTURE = "hfncap-" + "2" * 32
CANDIDATE = "hfncand-" + "3" * 32
REVISION = "a" * 40
BODY_ID = "body-" + "4" * 32


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _regions() -> dict[str, dict[str, object]]:
    return {
        region: {
            "source_image_sha256": _sha(f"source-{region}"),
            "uv_set_sha256": _sha(f"uv-{region}"),
            "mask_pixel_count": MIN_REGION_MASK_PIXELS + 20,
            "changed_pixel_count": MIN_REGION_CHANGED_PIXELS + 2,
            "max_observed_channel_delta_levels": MAX_CHANNEL_DELTA_LEVELS,
        }
        for region in REQUIRED_REGIONS
    }


def _receipt() -> dict[str, object]:
    regions = _regions()
    changed = sum(int(item["changed_pixel_count"]) for item in regions.values())
    return {
        "format": candidate.FORMAT,
        "version": candidate.VERSION,
        "policy_revision": candidate.POLICY_REVISION,
        "candidate_id": CANDIDATE,
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": CAPTURE,
        "body_id": BODY_ID,
        "bodyrig_revision": REVISION,
        "method": METHOD,
        "source_package_sha256": _sha("source-package"),
        "candidate_package_sha256": _sha("candidate-package"),
        "source_avatar_sha256": _sha("source-avatar"),
        "candidate_avatar_sha256": _sha("candidate-avatar"),
        "source_capture_sha256": _sha("source-capture"),
        "landmark_evidence_sha256": _sha("landmark"),
        "uv_evidence_sha256": _sha("uv-evidence"),
        "source_basecolor_sha256": _sha("source-basecolor"),
        "candidate_basecolor_sha256": _sha("candidate-basecolor"),
        "max_channel_delta_levels": MAX_CHANNEL_DELTA_LEVELS,
        "changed_pixel_count": changed,
        "changed_pixel_fraction": 0.001,
        "regions": regions,
        "geometry_surface_sha256": _sha("geometry"),
        "skinned_surface_sha256": _sha("skinned"),
        "rig_sha256": _sha("rig"),
        "uv_material_mapping_sha256": _sha("uv-mapping"),
        "clean_appearance_ab": True,
        "source_grounded": True,
        "generative": False,
        "package_application_authority": True,
        "geometry_modified": False,
        "texture_modified": True,
        "human_review_required": True,
        "production_activation": False,
    }


def _embedded() -> dict[str, object]:
    receipt = _receipt()
    return candidate._embedded_receipt(
        candidate_id=CANDIDATE,
        person_id=PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
        bodyrig_revision=REVISION,
        source_package_sha256=str(receipt["source_package_sha256"]),
        source_capture_sha256=str(receipt["source_capture_sha256"]),
        landmark_evidence_sha256=str(receipt["landmark_evidence_sha256"]),
        uv_evidence_sha256=str(receipt["uv_evidence_sha256"]),
        source_basecolor_sha256=str(receipt["source_basecolor_sha256"]),
        candidate_basecolor_sha256=str(receipt["candidate_basecolor_sha256"]),
        regions=receipt["regions"],
        fingerprints={
            "geometry_surface_sha256": receipt["geometry_surface_sha256"],
            "skinned_surface_sha256": receipt["skinned_surface_sha256"],
            "rig_sha256": receipt["rig_sha256"],
            "uv_material_mapping_sha256": receipt["uv_material_mapping_sha256"],
        },
    )


def test_candidate_validator_rejects_boolean_v1_and_preserves_numeric_v1() -> None:
    receipt = _receipt()
    receipt["version"] = True
    with pytest.raises(candidate.HandsFeetNailsDetailCandidateError, match="format/version"):
        candidate.validate_candidate_receipt(receipt)

    receipt = _receipt()
    receipt["version"] = 1.0
    assert candidate.validate_candidate_receipt(receipt)["version"] == 1.0


def test_embedded_candidate_receipt_rejects_bool_numeric_aliases() -> None:
    expected = _embedded()

    actual = dict(expected)
    actual["version"] = True
    assert candidate._embedded_receipt_matches(actual, expected) is False

    actual = dict(expected)
    actual["sourceGrounded"] = 1
    assert candidate._embedded_receipt_matches(actual, expected) is False

    actual = dict(expected)
    actual["productionActivation"] = 0
    assert candidate._embedded_receipt_matches(actual, expected) is False

    actual = dict(expected)
    actual["version"] = 1.0
    assert candidate._embedded_receipt_matches(actual, expected) is True


def _render_manifest(root: Path, *, version: object) -> Path:
    snapshots: list[dict[str, object]] = []
    for index, region in enumerate(REQUIRED_REGIONS):
        image_path = root / f"{region}.png"
        Image.new("RGB", (1024, 1024), (40 + index, 80, 120)).save(
            image_path,
            format="PNG",
            compress_level=9,
        )
        snapshots.append({
            "view": region,
            "file": image_path.name,
            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "width": 1024,
            "height": 1024,
        })
    path = root / "hands-feet-nails-render-set.json"
    path.write_text(json.dumps({
        "format": authority.RENDER_FORMAT,
        "version": version,
        "body_id": BODY_ID,
        "package_sha256": _sha("package"),
        "semantics": authority.RENDER_SEMANTICS,
        "snapshots": snapshots,
    }), encoding="utf-8")
    return path


def test_canonical_render_validator_rejects_boolean_v1_and_preserves_numeric_v1(tmp_path: Path) -> None:
    path = _render_manifest(tmp_path, version=True)
    with pytest.raises(authority.HandsFeetNailsAuthorityError, match="format/version"):
        authority.validate_render_manifest(
            path,
            body_id=BODY_ID,
            package_sha256=_sha("package"),
        )

    path = _render_manifest(tmp_path, version=1.0)
    result = authority.validate_render_manifest(
        path,
        body_id=BODY_ID,
        package_sha256=_sha("package"),
    )
    assert result["manifest"]["version"] == 1.0
