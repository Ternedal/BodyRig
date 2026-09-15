from __future__ import annotations

from pathlib import Path


def _source(name: str) -> str:
    return (Path(__file__).parents[1] / "bodyrig" / name).read_text(encoding="utf-8")


def test_sealed_pipeline_requires_and_propagates_calibration_provenance() -> None:
    source = _source("photoreal_calibration_provenance_pipeline.py")
    assert "validate_calibration_provenance" in source
    assert "authorize_frame_identities_sealed" in source
    assert "build_frame_index_sealed" in source
    assert "build_teacher_input_sealed" in source
    assert source.count("negative_inventory_sha256") >= 6
    assert source.count("identity_calibration_provenance_sha256") >= 6


def test_teacher_manifest_is_resealed_after_provenance_is_attached() -> None:
    source = _source("photoreal_calibration_provenance_pipeline.py")
    attach = source.index('result["identity_calibration_provenance_sha256"] = provenance_sha', source.index("def build_teacher_input_sealed"))
    reseal = source.index('result["teacher_input_sha256"] = _digest(result)', attach)
    assert attach < reseal


def test_legacy_core_only_artifacts_fail_closed_at_sealed_boundaries() -> None:
    source = _source("photoreal_calibration_provenance_pipeline.py")
    assert 'authorized_observations.get("negative_inventory_sha256")' in source
    assert 'authorized_observations.get("identity_calibration_provenance_sha256")' in source
    assert 'frame_index.get("negative_inventory_sha256")' in source
    assert 'frame_index.get("identity_calibration_provenance_sha256")' in source
