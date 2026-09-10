from __future__ import annotations

from bodyrig.photoidentity_schp_contract import CAPABILITIES, UNSUPPORTED_IDENTITY_DOMAINS
from bodyrig.photoidentity_schp_detail import analyze_schp_detail


def _seg() -> list[list[int]]:
    return [[0 for _ in range(512)] for _ in range(512)]


def _fill(seg: list[list[int]], label: int, x0: int, y0: int, x1: int, y1: int) -> None:
    for y in range(y0, y1):
        seg[y][x0:x1] = [label] * (x1 - x0)


def _observation(**changes) -> dict[str, object]:
    value: dict[str, object] = {
        "target_confidence": 0.95,
        "face_visibility": 0.95,
        "full_body_visibility": 0.95,
        "sharpness": 0.95,
        "occlusion": 0.05,
        "view": "front",
    }
    value.update(changes)
    return value


def test_schp_contract_only_grants_hair_and_skin_source_observability() -> None:
    assert CAPABILITIES == ("hair-detail", "skin-detail")
    assert set(UNSUPPORTED_IDENTITY_DOMAINS) == {
        "body_rear",
        "torso_chest",
        "waist_hips",
        "fingernails_detail",
        "toenails_detail",
    }


def test_hair_requires_real_hair_face_boundary_and_source_resolution() -> None:
    seg = _seg()
    _fill(seg, 2, 160, 60, 350, 180)   # hair
    _fill(seg, 11, 190, 160, 325, 300)  # face touching/overlapping hair x-range
    claims = analyze_schp_detail(
        seg,
        scene_id="scene-a",
        observation=_observation(),
        source_width=1920,
        source_height=1080,
    )
    assert claims["hair_hairline"][0]["quality"] >= 0.8

    separated = _seg()
    _fill(separated, 2, 10, 10, 80, 80)
    _fill(separated, 11, 300, 250, 380, 340)
    missing = analyze_schp_detail(
        separated,
        scene_id="scene-a",
        observation=_observation(),
        source_width=1920,
        source_height=1080,
    )
    assert "hair_hairline" not in missing


def test_skin_requires_face_plus_multiple_exposed_limb_regions() -> None:
    seg = _seg()
    _fill(seg, 11, 210, 60, 310, 160)   # face
    _fill(seg, 14, 120, 170, 190, 390)  # left arm
    _fill(seg, 15, 330, 170, 400, 390)  # right arm
    _fill(seg, 12, 200, 350, 255, 505)  # left leg
    _fill(seg, 13, 260, 350, 315, 505)  # right leg
    claims = analyze_schp_detail(
        seg,
        scene_id="scene-b",
        observation=_observation(),
        source_width=1920,
        source_height=1080,
    )
    assert claims["skin_detail"][0]["quality"] >= 0.8

    face_only = _seg()
    _fill(face_only, 11, 210, 60, 310, 160)
    missing = analyze_schp_detail(
        face_only,
        scene_id="scene-b",
        observation=_observation(),
        source_width=1920,
        source_height=1080,
    )
    assert "skin_detail" not in missing


def test_schp_never_synthesizes_anatomy_or_nail_claims() -> None:
    seg = _seg()
    _fill(seg, 2, 160, 60, 350, 180)
    _fill(seg, 11, 190, 160, 325, 300)
    _fill(seg, 14, 120, 170, 190, 390)
    _fill(seg, 15, 330, 170, 400, 390)
    claims = analyze_schp_detail(
        seg,
        scene_id="scene-c",
        observation=_observation(),
        source_width=3840,
        source_height=2160,
    )
    assert "torso_chest" not in claims
    assert "waist_hips" not in claims
    assert "fingernails_detail" not in claims
    assert "toenails_detail" not in claims
    assert "body_rear" not in claims


def test_blurry_source_can_be_detected_but_cannot_qualify_for_sufficiency() -> None:
    seg = _seg()
    _fill(seg, 2, 160, 60, 350, 180)
    _fill(seg, 11, 190, 160, 325, 300)
    claim = analyze_schp_detail(
        seg,
        scene_id="scene-d",
        observation=_observation(sharpness=0.45),
        source_width=1920,
        source_height=1080,
    )["hair_hairline"][0]
    assert claim["quality"] == 0.45
