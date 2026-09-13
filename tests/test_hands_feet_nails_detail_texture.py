from __future__ import annotations

from PIL import Image

import bodyrig.hands_feet_nails_detail_texture as subject


def _subtle_source(size: int = 64) -> Image.Image:
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            value = 104 if (x + y) % 2 == 0 else 120
            pixels[x, y] = (value, value, value)
    return image


def test_residual_map_is_bounded_and_source_derived() -> None:
    residual = subject._residual_map(_subtle_source())
    values = list(residual.getdata())

    assert min(values) >= 128 - subject.MAX_CHANNEL_DELTA_LEVELS
    assert max(values) <= 128 + subject.MAX_CHANNEL_DELTA_LEVELS
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
    assert 1 <= observed_max <= subject.MAX_CHANNEL_DELTA_LEVELS
    for y in range(32):
        for x in range(32):
            before = base.getpixel((x, y))
            after = result.getpixel((x, y))
            if not (8 <= x < 24 and 8 <= y < 24):
                assert after == before
            elif after != before:
                deltas = tuple(after[index] - before[index] for index in range(3))
                assert deltas[0] == deltas[1] == deltas[2]
                assert abs(deltas[0]) <= subject.MAX_CHANNEL_DELTA_LEVELS


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
