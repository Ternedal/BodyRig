from __future__ import annotations

import pytest

from bodyrig.package import MRBodyError, build_package, validate_manifest, validate_provenance


def _manifest(builder_version: str) -> dict[str, object]:
    return {
        "format": "modelrig-body",
        "format_version": 1,
        "id": "metadata-unicode",
        "name": "Metadata Unicode",
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": builder_version},
    }


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


def test_builder_version_rejects_lone_surrogate() -> None:
    with pytest.raises(MRBodyError, match="manifest.json: invalid builder identity"):
        validate_manifest(_manifest("\ud83d"))


def test_provenance_created_at_rejects_lone_surrogate() -> None:
    with pytest.raises(MRBodyError, match="provenance.json: invalid created_at"):
        validate_provenance(_provenance(created_at="\ud83d"))


@pytest.mark.parametrize("field", ["stage", "adapter", "revision"])
def test_pipeline_text_rejects_lone_surrogate(field: str) -> None:
    with pytest.raises(MRBodyError, match="provenance.json: invalid pipeline stage"):
        validate_provenance(_provenance(**{field: "\ud83d"}))


def test_package_metadata_keeps_valid_supplementary_unicode() -> None:
    manifest = validate_manifest(_manifest("v1-😀"))
    provenance = validate_provenance(
        _provenance(
            created_at="2026-09-12T00:00:00Z😀",
            stage="stage-😀",
            adapter="adapter-😀",
            revision="revision-😀",
        )
    )

    assert manifest["builder"]["version"] == "v1-😀"
    assert provenance["created_at"].endswith("😀")
    assert all(value.endswith("😀") for value in provenance["pipeline"][0].values())


def test_build_package_rejects_invalid_builder_version_before_serialization(tmp_path) -> None:
    with pytest.raises(MRBodyError, match="manifest.json: invalid builder identity"):
        build_package(
            tmp_path / "invalid-builder-version.mrbody",
            body_id="metadata-unicode",
            name="Metadata Unicode",
            avatar_vrm=b"not-reached",
            bodyprint={},
            provenance={},
            thumbnail_png=b"not-reached",
            builder_version="\ud83d",
        )


def test_build_package_rejects_invalid_provenance_before_serialization(tmp_path) -> None:
    bodyprint = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {"energy": 0.5},
    }
    with pytest.raises(MRBodyError, match="provenance.json: invalid created_at"):
        build_package(
            tmp_path / "invalid-provenance.mrbody",
            body_id="metadata-unicode",
            name="Metadata Unicode",
            avatar_vrm=b"not-reached",
            bodyprint=bodyprint,
            provenance=_provenance(created_at="\ud83d"),
            thumbnail_png=b"not-reached",
        )
