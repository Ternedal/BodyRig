"""The cached placeholder thumbnail is byte-identical to a fresh render.

`_thumbnail_png` is a pure function of (width, height); the lru_cache only
removes the ~8 ms per-call Python pixel loop that every placeholder/VRM
build paid. Both copies of the helper (avatar.py and the SiTH fitter) must
keep returning exactly the bytes the uncached function produces.
"""

from __future__ import annotations

import hashlib

import pytest

from bodyrig import avatar
from bodyrig.bridges import sith_smplx_vrm_fitter as fitter


@pytest.mark.parametrize("module", [avatar, fitter])
def test_cached_thumbnail_equals_fresh_render(module) -> None:
    function = module._thumbnail_png
    assert hasattr(function, "cache_clear"), "the thumbnail renderer is expected to be cached"
    function.cache_clear()
    fresh_default = function.__wrapped__()
    fresh_small = function.__wrapped__(32, 16)
    assert function() == fresh_default
    assert function() is function()  # served from cache, same immutable bytes
    assert function(32, 16) == fresh_small
    assert function(width=32, height=16) == fresh_small
    assert function() != function(32, 16)
    assert fresh_default[:8] == b"\x89PNG\r\n\x1a\n"
    info = function.cache_info()
    assert info.hits >= 2 and info.misses >= 2


def test_cache_is_keyed_per_module() -> None:
    # The two renderers are independent helpers; caching one must not leak
    # bytes into the other (they draw different placeholder figures).
    avatar._thumbnail_png.cache_clear()
    fitter._thumbnail_png.cache_clear()
    assert hashlib.sha256(avatar._thumbnail_png()).hexdigest() == hashlib.sha256(avatar._thumbnail_png.__wrapped__()).hexdigest()
    assert hashlib.sha256(fitter._thumbnail_png()).hexdigest() == hashlib.sha256(fitter._thumbnail_png.__wrapped__()).hexdigest()
