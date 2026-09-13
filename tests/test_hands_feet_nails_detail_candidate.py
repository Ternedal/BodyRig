from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image

import bodyrig.hands_feet_nails_detail_candidate as subject
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
        "format": subject.FORMAT,
        "version": subject.VERSION,
        "policy_revision": subject.POLICY_REVISION,
        "candidate_id": CANDIDATE,
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": CAPTURE,
        "body_id": "body-example",
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


def test_candidate_receipt_preserves_application_review_boundary() -> None:
    result = subject.validate_candidate_receipt(_receipt())

    assert result["source_grounded"] is True
    assert result["generative"] is False
    assert result["package_application_authority"] is True
    assert result["geometry_modified"] is False
    assert result["texture_modified"] is True
    assert result["human_review_required"] is True
    assert result["production_activation"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("clean_appearance_ab", False),
        ("source_grounded", False),
        ("generative", True),
        ("package_application_authority", False),
        ("geometry_modified", True),
        ("texture_modified", False),
        ("human_review_required", False),
        ("production_activation", True),
    ],
)
def test_candidate_receipt_rejects_authority_boundary_drift(field: str, value: object) -> None:
    receipt = _receipt()
    receipt[field] = value

    with pytest.raises(subject.HandsFeetNailsDetailCandidateError, match="boundary"):
        subject.validate_candidate_receipt(receipt)


def test_candidate_receipt_requires_changed_package_and_basecolor_bytes() -> None:
    receipt = _receipt()
    receipt["candidate_package_sha256"] = receipt["source_package_sha256"]
    with pytest.raises(subject.HandsFeetNailsDetailCandidateError, match="package bytes"):
        subject.validate_candidate_receipt(receipt)

    receipt = _receipt()
    receipt["candidate_basecolor_sha256"] = receipt["source_basecolor_sha256"]
    with pytest.raises(subject.HandsFeetNailsDetailCandidateError, match="base-color bytes"):
        subject.validate_candidate_receipt(receipt)


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), (90, 120, 150)).save(output, format="PNG")
    return output.getvalue()


def _document(png: bytes, *, embedded: bool = False) -> dict[str, object]:
    bodyrig: dict[str, object] = {
        "appearanceTransfer": {"activeBaseColorSha256": hashlib.sha256(png).hexdigest()}
    }
    if embedded:
        bodyrig["handsFeetNailsDetailApplication"] = {"format": "already-applied"}
    return {
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
        "extras": {"bodyrig": bodyrig},
    }


def test_active_basecolor_requires_exact_appearance_hash_and_rejects_reapplication() -> None:
    png = _png_bytes()
    document = _document(png)

    raw, _image, _views, _bodyrig, appearance = subject._active_basecolor(
        document,
        png,
        reject_existing_application=True,
    )
    assert raw == png
    assert appearance["activeBaseColorSha256"] == hashlib.sha256(png).hexdigest()

    tampered = _document(png)
    tampered["extras"]["bodyrig"]["appearanceTransfer"]["activeBaseColorSha256"] = "0" * 64
    with pytest.raises(subject.HandsFeetNailsDetailCandidateError, match="appearanceTransfer"):
        subject._active_basecolor(tampered, png, reject_existing_application=True)

    with pytest.raises(subject.HandsFeetNailsDetailCandidateError, match="already applied"):
        subject._active_basecolor(_document(png, embedded=True), png, reject_existing_application=True)


def test_embedded_receipt_never_claims_release_or_production_authority() -> None:
    receipt = _receipt()
    embedded = subject._embedded_receipt(
        candidate_id=CANDIDATE,
        person_id=PERSON,
        body_revision=BODY,
        capture_id=CAPTURE,
        bodyrig_revision=REVISION,
        source_package_sha256=receipt["source_package_sha256"],
        source_capture_sha256=receipt["source_capture_sha256"],
        landmark_evidence_sha256=receipt["landmark_evidence_sha256"],
        uv_evidence_sha256=receipt["uv_evidence_sha256"],
        source_basecolor_sha256=receipt["source_basecolor_sha256"],
        candidate_basecolor_sha256=receipt["candidate_basecolor_sha256"],
        regions=receipt["regions"],
        fingerprints={
            "geometry_surface_sha256": receipt["geometry_surface_sha256"],
            "skinned_surface_sha256": receipt["skinned_surface_sha256"],
            "rig_sha256": receipt["rig_sha256"],
            "uv_material_mapping_sha256": receipt["uv_material_mapping_sha256"],
        },
    )

    assert embedded["packageApplicationAuthority"] is True
    assert embedded["humanReviewRequired"] is True
    assert embedded["productionActivation"] is False
    assert embedded["geometryModified"] is False
    assert embedded["textureModified"] is True
    assert embedded["generative"] is False
