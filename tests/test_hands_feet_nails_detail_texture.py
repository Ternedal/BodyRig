from __future__ import annotations

from PIL import Image

import bodyrig.hands_feet_nails_detail_texture as subject


def _subtle_source(size: int = 64) -> Image.Image:
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            value = 104 if ((x // 8) + (y // 8)) % 2 == 0 else 120
            pixels[x, y] = (value, value, value)
    return image


def test_method_is_landmark_driven_v3_for_fingernails_and_toenails() -> None:
    assert subject.METHOD == "source-landmark-fingernail-toenail-residual-skinned-uv-v3"
    assert subject.MAX_CHANNEL_DELTA_LEVELS > subject.RESIDUAL_MAX_CHANNEL_DELTA_LEVELS
    assert set(subject.HAND_NAIL_JOINTS["left_hand"]) == {
        "thumb", "index", "middle", "ring", "pinky"
    }
    assert set(subject.HAND_NAIL_JOINTS["right_hand"]) == {
        "thumb", "index", "middle", "ring", "pinky"
    }
    assert tuple(subject.FOOT_REGIONS) == ("left_foot", "right_foot")
    assert tuple(subject.TOE_LABELS) == ("big_toe", "toe_2", "toe_3", "toe_4", "small_toe")


def test_residual_map_is_bounded_and_source_derived() -> None:
    residual = subject._residual_map(_subtle_source())
    values = list(residual.tobytes())

    assert min(values) >= 128 - subject.RESIDUAL_MAX_CHANNEL_DELTA_LEVELS
    assert max(values) <= 128 + subject.RESIDUAL_MAX_CHANNEL_DELTA_LEVELS
    assert any(value != 128 for value in values)


def test_apply_region_changes_only_masked_pixels_and_preserves_chroma_delta() -> None:
    base = Image.new("RGB", (32, 32), (80, 120, 160))
    mask = Image.new("L", (32, 32), 0)
    mask.paste(255, (8, 8, 24, 24))

    result, changed, observed_max = subject._apply_region(
        base,
        mask=mask,
        source=_subtle_source(),
    )

    assert changed >= subject.MIN_REGION_CHANGED_PIXELS
    assert 1 <= observed_max <= subject.RESIDUAL_MAX_CHANNEL_DELTA_LEVELS
    for y in range(32):
        for x in range(32):
            before = base.getpixel((x, y))
            after = result.getpixel((x, y))
            if not (8 <= x < 24 and 8 <= y < 24):
                assert after == before
            elif after != before:
                deltas = tuple(after[index] - before[index] for index in range(3))
                assert deltas[0] == deltas[1] == deltas[2]
                assert abs(deltas[0]) <= subject.RESIDUAL_MAX_CHANNEL_DELTA_LEVELS


def test_apply_region_fails_closed_when_source_has_no_local_detail() -> None:
    base = Image.new("RGB", (32, 32), (100, 120, 140))
    mask = Image.new("L", (32, 32), 0)
    mask.paste(255, (8, 8, 24, 24))
    flat_source = Image.new("RGB", (64, 64), (120, 120, 120))

    try:
        subject._apply_region(base, mask=mask, source=flat_source)
    except subject.HandsFeetNailsDetailTextureError as exc:
        assert "does not contain enough bounded local detail" in str(exc)
    else:
        raise AssertionError("flat source detail must fail closed")


def test_landmark_patch_is_centered_on_projected_nail_tip() -> None:
    source = Image.new("RGB", (100, 100), (20, 30, 40))
    pixels = source.load()
    for y in range(44, 57):
        for x in range(69, 82):
            pixels[x, y] = (210, 160, 150)

    patch = subject._landmark_patch(
        source,
        {"x_norm": 0.75, "y_norm": 0.50, "confidence": 0.99},
    )

    assert patch.size[0] >= 4 and patch.size[1] >= 4
    values = list(patch.getdata())
    assert (210, 160, 150) in values


def test_apply_nail_patch_changes_only_nail_mask_and_is_bounded() -> None:
    base = Image.new("RGB", (32, 32), (100, 110, 120))
    mask = Image.new("L", (32, 32), 0)
    mask.paste(255, (10, 8, 22, 24))
    patch = Image.new("RGB", (16, 16), (220, 170, 160))

    result = subject._apply_nail_patch(base, mask=mask, patch=patch)

    changed = 0
    for y in range(32):
        for x in range(32):
            before = base.getpixel((x, y))
            after = result.getpixel((x, y))
            if not (10 <= x < 22 and 8 <= y < 24):
                assert after == before
                continue
            if after != before:
                changed += 1
                assert max(abs(after[i] - before[i]) for i in range(3)) <= subject.MAX_CHANNEL_DELTA_LEVELS
    assert changed > 0
