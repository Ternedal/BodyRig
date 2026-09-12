from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.package import MRBodyError, build_package, validate_provenance


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts" / "provenance-v1.schema.json").read_text(encoding="utf-8"))


def _provenance(*, created_at: str = "2026-09-12T00:00:00Z", **pipeline_overrides: str) -> dict[str, object]:
    pipeline = {
        "stage": "body-recovery",
        "adapter": "fixture",
        "revision": "fixture-v1",
    }
    pipeline.update(pipeline_overrides)
    return {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": created_at,
        "source": {"kind": "user-supplied-local-media", "count": 1},
        "synthetic_avatar": True,
        "pipeline": [pipeline],
    }


def test_created_at_length_matches_schema_boundary() -> None:
    limit = SCHEMA["properties"]["created_at"]["maxLength"]
    assert limit == 80
    assert validate_provenance(_provenance(created_at="😀" * limit))["created_at"] == "😀" * limit
    with pytest.raises(MRBodyError, match="provenance.json: invalid created_at"):
        validate_provenance(_provenance(created_at="😀" * (limit + 1)))


@pytest.mark.parametrize("field", ["stage", "adapter", "revision"])
def test_pipeline_text_length_matches_schema_boundary(field: str) -> None:
    item_schema = SCHEMA["properties"]["pipeline"]["items"]["properties"]
    limit = item_schema[field]["maxLength"]
    expected = {"stage": 80, "adapter": 120, "revision": 160}[field]
    assert limit == expected

    accepted = validate_provenance(_provenance(**{field: "😀" * limit}))
    assert accepted["pipeline"][0][field] == "😀" * limit

    with pytest.raises(MRBodyError, match="provenance.json: invalid pipeline stage"):
        validate_provenance(_provenance(**{field: "😀" * (limit + 1)}))


def test_build_package_rejects_overlong_provenance_before_avatar_validation(tmp_path: Path) -> None:
    limit = SCHEMA["properties"]["created_at"]["maxLength"]
    bodyprint = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {"energy": 0.5},
    }
    with pytest.raises(MRBodyError, match="provenance.json: invalid created_at"):
        build_package(
            tmp_path / "overlong-provenance.mrbody",
            body_id="provenance-length",
            name="Provenance Length",
            avatar_vrm=b"not-reached",
            bodyprint=bodyprint,
            provenance=_provenance(created_at="x" * (limit + 1)),
            thumbnail_png=b"not-reached",
        )
