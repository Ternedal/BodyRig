from __future__ import annotations

import json

import pytest

import bodyrig.photoreal_frame_index_sealed_authority as boundary
from bodyrig.photoreal_frame_identity_output_provenance import seal_frame_identity_authority


def _artifact() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-authorized-observations",
        "version": 1,
        "performer_id": "42",
        "identity_matching_calibrated": True,
        "identity_match_threshold": 0.8,
        "observations": [{"candidate_id": "person-0", "target_identity_verified": True}],
        "identity_authority_is_core_derived": True,
        "multi_candidate_identity_safe": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }


def _write_json(path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_sealed_frame_index_boundary_carries_verified_authority_digest(tmp_path, monkeypatch) -> None:
    plan = tmp_path / "plan.json"
    receipt = tmp_path / "receipt.json"
    observations = tmp_path / "observations.json"
    output = tmp_path / "frame-index.json"
    _write_json(plan, {})
    _write_json(receipt, {})
    sealed = seal_frame_identity_authority(_artifact())
    _write_json(observations, sealed)

    calls: list[tuple[object, object, object]] = []

    def fake_build_frame_index(plan_value, receipt_value, observations_value):
        calls.append((plan_value, receipt_value, observations_value))
        return {"format": "bodyrig-photoreal-frame-index", "version": 1}

    monkeypatch.setattr(boundary, "build_frame_index", fake_build_frame_index)

    result = boundary.build_frame_index_files_sealed(plan, receipt, observations, output)

    assert len(calls) == 1
    assert result["source_frame_identity_authority_sha256"] == sealed["frame_identity_authority_sha256"]
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["source_frame_identity_authority_sha256"] == sealed["frame_identity_authority_sha256"]


def test_sealed_frame_index_boundary_rejects_tamper_before_core_builder(tmp_path, monkeypatch) -> None:
    plan = tmp_path / "plan.json"
    receipt = tmp_path / "receipt.json"
    observations = tmp_path / "observations.json"
    output = tmp_path / "frame-index.json"
    _write_json(plan, {})
    _write_json(receipt, {})
    sealed = seal_frame_identity_authority(_artifact())
    sealed["observations"][0]["target_identity_verified"] = False
    _write_json(observations, sealed)

    called = False

    def forbidden_build_frame_index(*_args):
        nonlocal called
        called = True
        raise AssertionError("core builder must not run after seal failure")

    monkeypatch.setattr(boundary, "build_frame_index", forbidden_build_frame_index)

    with pytest.raises(boundary.PhotorealFrameIndexSealedAuthorityError, match="digest mismatch"):
        boundary.build_frame_index_files_sealed(plan, receipt, observations, output)

    assert called is False
    assert not output.exists()


def test_sealed_frame_index_boundary_rejects_missing_seal_before_core_builder(tmp_path, monkeypatch) -> None:
    plan = tmp_path / "plan.json"
    receipt = tmp_path / "receipt.json"
    observations = tmp_path / "observations.json"
    output = tmp_path / "frame-index.json"
    _write_json(plan, {})
    _write_json(receipt, {})
    _write_json(observations, _artifact())

    called = False

    def forbidden_build_frame_index(*_args):
        nonlocal called
        called = True
        raise AssertionError("core builder must not run without seal")

    monkeypatch.setattr(boundary, "build_frame_index", forbidden_build_frame_index)

    with pytest.raises(boundary.PhotorealFrameIndexSealedAuthorityError, match="missing or invalid"):
        boundary.build_frame_index_files_sealed(plan, receipt, observations, output)

    assert called is False
    assert not output.exists()
