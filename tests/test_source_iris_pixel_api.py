from __future__ import annotations

import warnings

from PIL import Image

from bodyrig.source_iris_isolation import _pixel_values


class _ModernPixels:
    def __init__(self) -> None:
        self.modern_called = False

    def get_flattened_data(self) -> list[int]:
        self.modern_called = True
        return [0, 255, 7]

    def getdata(self) -> list[int]:
        raise AssertionError("deprecated getdata fallback must not run when modern Pillow API exists")


class _LegacyPixels:
    def getdata(self) -> list[int]:
        return [1, 2, 3]


def test_pixel_values_prefers_modern_pillow_api() -> None:
    image = _ModernPixels()
    assert list(_pixel_values(image)) == [0, 255, 7]
    assert image.modern_called is True


def test_pixel_values_keeps_legacy_pillow_compatibility() -> None:
    assert list(_pixel_values(_LegacyPixels())) == [1, 2, 3]


def test_current_pillow_path_emits_no_getdata_deprecation_warning() -> None:
    image = Image.new("L", (2, 2), 255)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert list(_pixel_values(image)) == [255, 255, 255, 255]
    assert not [item for item in caught if issubclass(item.category, DeprecationWarning)]
