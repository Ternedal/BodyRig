from __future__ import annotations

import math

import pytest

from bodyrig.photoidentity_schp_contract import ADAPTER, ADAPTER_REVISION
from bodyrig.photoidentity_schp_runner import PhotoIdentitySchpRunnerError, _merge_best


def _claim(*, scene_id: str = "scene-1", quality: float = 0.9) -> dict[str, object]:
    return {
        "scene_id": scene_id,
        "quality": quality,
        "source_derived": True,
        "adapter": ADAPTER,
        "revision": ADAPTER_REVISION,
    }


def test_merge_accepts_exact_pinned_source_claim() -> None:
    destination: dict[str, list[dict[str, object]]] = {}
    _merge_best(
        destination,
        {"hair_hairline": [_claim()]},
        expected_scene_id="scene-1",
    )
    assert destination["hair_hairline"] == [_claim()]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"scene_id": "scene-2"}, "unexpected scene"),
        ({"source_derived": False}, "not source-derived"),
        ({"adapter": "other"}, "pinned adapter authority"),
        ({"revision": "999"}, "pinned adapter authority"),
    ],
)
def test_merge_rejects_claims_outside_exact_authority(mutation: dict[str, object], match: str) -> None:
    claim = _claim()
    claim.update(mutation)
    with pytest.raises(PhotoIdentitySchpRunnerError, match=match):
        _merge_best({}, {"hair_hairline": [claim]}, expected_scene_id="scene-1")


@pytest.mark.parametrize("quality", [math.nan, math.inf, -0.01, 1.01, True])
def test_merge_rejects_nonfinite_or_out_of_range_quality(quality: object) -> None:
    claim = _claim()
    claim["quality"] = quality
    with pytest.raises(PhotoIdentitySchpRunnerError, match="quality"):
        _merge_best({}, {"skin_detail": [claim]}, expected_scene_id="scene-1")


def test_merge_rejects_anatomy_or_nail_overclaim() -> None:
    for domain in ("torso_chest", "waist_hips", "fingernails_detail", "toenails_detail"):
        with pytest.raises(PhotoIdentitySchpRunnerError, match="unsupported domain"):
            _merge_best({}, {domain: [_claim()]}, expected_scene_id="scene-1")


def test_merge_keeps_best_claim_per_scene_only() -> None:
    destination: dict[str, list[dict[str, object]]] = {}
    _merge_best(destination, {"hair_hairline": [_claim(quality=0.71)]}, expected_scene_id="scene-1")
    _merge_best(destination, {"hair_hairline": [_claim(quality=0.88)]}, expected_scene_id="scene-1")
    assert len(destination["hair_hairline"]) == 1
    assert destination["hair_hairline"][0]["quality"] == 0.88
