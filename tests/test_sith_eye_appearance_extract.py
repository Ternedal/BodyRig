import pytest

from bodyrig.bridges.sith_eye_appearance_extract import (
    EyeAppearanceExtractError,
    build_receipt,
    eye_uv_face_indices,
)


SHA = "a" * 64


def test_eye_uv_face_indices_bind_selected_canonical_faces() -> None:
    bound = [
        [(0, 10), (1, 11), (2, 12)],
        [(2, 13), (3, 14), (4, 15)],
        [(5, 20), (6, 21), (7, 22)],
    ]

    assert eye_uv_face_indices(bound_faces=bound, selected_faces=[0, 2]) == [
        (10, 11, 12),
        (20, 21, 22),
    ]


def test_eye_uv_face_indices_reject_duplicate_selection() -> None:
    bound = [[(0, 1), (1, 2), (2, 3)]]

    with pytest.raises(EyeAppearanceExtractError, match="duplicates"):
        eye_uv_face_indices(bound_faces=bound, selected_faces=[0, 0])


def test_eye_appearance_receipt_is_partial_and_review_only() -> None:
    receipt = build_receipt(
        target_family="female",
        donor_sha256=SHA,
        reconstruction_sha256=SHA,
        source_mesh_sha256=SHA,
        source_texture_sha256=SHA,
        canonical_bake_sha256=SHA,
        left_png_sha256=SHA,
        right_png_sha256=SHA,
        left_face_count=12,
        right_face_count=12,
        left_mask_pixels=120,
        right_mask_pixels=118,
    )

    assert receipt["sourceDerivedEyeSurfaceAppearance"] is True
    assert receipt["irisIdentityIsolated"] is False
    assert receipt["irisAppearanceStatus"] == "review-pending"
    assert receipt["cornealMaterialStatus"] == "missing"
    assert receipt["eyelashStatus"] == "missing"
    assert receipt["componentStatus"] == "partial"
    assert receipt["comparisonOnly"] is True
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False


def test_eye_appearance_receipt_rejects_bad_digest() -> None:
    with pytest.raises(EyeAppearanceExtractError, match="SHA-256"):
        build_receipt(
            target_family="female",
            donor_sha256="bad",
            reconstruction_sha256=SHA,
            source_mesh_sha256=SHA,
            source_texture_sha256=SHA,
            canonical_bake_sha256=SHA,
            left_png_sha256=SHA,
            right_png_sha256=SHA,
            left_face_count=12,
            right_face_count=12,
            left_mask_pixels=120,
            right_mask_pixels=118,
        )
