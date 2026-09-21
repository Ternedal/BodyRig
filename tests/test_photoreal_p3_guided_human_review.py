from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p3_guided_human_review as guided
from bodyrig.photoreal_p3_device_distillation_plan import FIDELITY_DELTA_DIMENSIONS
from bodyrig.photoreal_p3_guided_human_review import (
    PhotorealP3GuidedHumanReviewError,
    _parse_decisions,
    build_reviewed_physical_evidence,
    write_reviewed_physical_evidence,
)


PLAN_SHA = "a" * 64


def _plan() -> dict:
    return {
        "p3_device_runtime_review_plan_sha256": PLAN_SHA,
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
    }


def _prefill() -> dict:
    return {
        "format": "bodyrig-photoreal-p3-physical-runtime-evidence",
        "version": 1,
        "operator_supplied": False,
        "runtime_review_plan_sha256": PLAN_SHA,
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
        "physical_device_observed": True,
        "installed_student_artifacts": [
            {"relative_path": "student.vrm", "sha256": "b" * 64}
        ],
        "observed_refresh_hz": 72.0,
        "p95_frame_time_ms": 11.0,
        "stereo_rendering_observed": True,
        "vr_safe_frame_pacing_observed": True,
        "installed_student_hashes_verified_on_device": True,
        "visual_results": [
            {"criterion": criterion, "decision": "REVIEW_REQUIRED"}
            for criterion in FIDELITY_DELTA_DIMENSIONS
        ],
        "reviewed_by": "REVIEW_REQUIRED",
        "review_notes": "Machine-safe prefill",
        "confirm_physical_device_review_complete": False,
    }


def _decisions(value: str = "pass") -> dict[str, str]:
    return {criterion: value for criterion in FIDELITY_DELTA_DIMENSIONS}


def _patch_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        guided,
        "validate_device_runtime_review_plan",
        lambda value: dict(value),
    )

    def validate_evidence(value, *, runtime_review_plan):
        assert runtime_review_plan["p3_device_runtime_review_plan_sha256"] == PLAN_SHA
        return copy.deepcopy(dict(value))

    monkeypatch.setattr(guided, "validate_physical_runtime_evidence", validate_evidence)


def test_parse_decisions_requires_exact_complete_universe() -> None:
    tokens = [f"{criterion}=pass" for criterion in FIDELITY_DELTA_DIMENSIONS]
    parsed = _parse_decisions(tokens)
    assert parsed == _decisions()

    with pytest.raises(PhotorealP3GuidedHumanReviewError, match="missing"):
        _parse_decisions(tokens[:-1])

    with pytest.raises(PhotorealP3GuidedHumanReviewError, match="more than once"):
        _parse_decisions(tokens + [tokens[0]])

    with pytest.raises(PhotorealP3GuidedHumanReviewError, match="unknown"):
        _parse_decisions(tokens[:-1] + ["not_a_dimension=pass"])


def test_guided_review_changes_only_human_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_validators(monkeypatch)
    prefill = _prefill()
    result = build_reviewed_physical_evidence(
        _plan(),
        prefill,
        decisions=_decisions(),
        reviewed_by="Anders",
        review_notes="Reviewed physically in Quest 2.",
        confirm_physical_device_review_complete=True,
    )

    assert result["operator_supplied"] is True
    assert result["confirm_physical_device_review_complete"] is True
    assert result["reviewed_by"] == "Anders"
    assert all(item["decision"] == "pass" for item in result["visual_results"])
    for field in (
        "runtime_review_plan_sha256",
        "target_device_family",
        "target_device_model",
        "physical_device_observed",
        "installed_student_artifacts",
        "observed_refresh_hz",
        "p95_frame_time_ms",
        "stereo_rendering_observed",
        "vr_safe_frame_pacing_observed",
        "installed_student_hashes_verified_on_device",
    ):
        assert result[field] == prefill[field]


def test_guided_review_requires_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_validators(monkeypatch)
    with pytest.raises(
        PhotorealP3GuidedHumanReviewError,
        match="completion confirmation",
    ):
        build_reviewed_physical_evidence(
            _plan(),
            _prefill(),
            decisions=_decisions(),
            reviewed_by="reviewer",
            review_notes="notes",
            confirm_physical_device_review_complete=False,
        )


def test_guided_review_rejects_already_edited_machine_prefill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_validators(monkeypatch)
    prefill = _prefill()
    prefill["visual_results"][0]["decision"] = "pass"

    with pytest.raises(
        PhotorealP3GuidedHumanReviewError,
        match="already edited or reordered",
    ):
        build_reviewed_physical_evidence(
            _plan(),
            prefill,
            decisions=_decisions(),
            reviewed_by="reviewer",
            review_notes="notes",
            confirm_physical_device_review_complete=True,
        )


def test_guided_review_rejects_prefill_that_already_claims_operator_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_validators(monkeypatch)
    prefill = _prefill()
    prefill["operator_supplied"] = True

    with pytest.raises(
        PhotorealP3GuidedHumanReviewError,
        match="operator_supplied=false",
    ):
        build_reviewed_physical_evidence(
            _plan(),
            prefill,
            decisions=_decisions(),
            reviewed_by="reviewer",
            review_notes="notes",
            confirm_physical_device_review_complete=True,
        )


def test_write_is_create_only_and_reuse_requires_exact_same_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_validators(monkeypatch)
    plan_path = tmp_path / "plan.json"
    prefill_path = tmp_path / "prefill.json"
    output = tmp_path / "reviewed.json"
    plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
    prefill_path.write_text(json.dumps(_prefill()), encoding="utf-8")

    first = write_reviewed_physical_evidence(
        plan_path,
        prefill_path,
        output_path=output,
        decisions=_decisions(),
        reviewed_by="reviewer",
        review_notes="exact notes",
        confirm_physical_device_review_complete=True,
    )
    assert output.is_file()

    with pytest.raises(
        PhotorealP3GuidedHumanReviewError,
        match="already exists",
    ):
        write_reviewed_physical_evidence(
            plan_path,
            prefill_path,
            output_path=output,
            decisions=_decisions(),
            reviewed_by="reviewer",
            review_notes="exact notes",
            confirm_physical_device_review_complete=True,
        )

    reused = write_reviewed_physical_evidence(
        plan_path,
        prefill_path,
        output_path=output,
        decisions=_decisions(),
        reviewed_by="reviewer",
        review_notes="exact notes",
        confirm_physical_device_review_complete=True,
        reuse_existing=True,
    )
    assert reused == first

    changed = _decisions()
    changed[FIDELITY_DELTA_DIMENSIONS[0]] = "fail"
    with pytest.raises(
        PhotorealP3GuidedHumanReviewError,
        match="differs from the exact current",
    ):
        write_reviewed_physical_evidence(
            plan_path,
            prefill_path,
            output_path=output,
            decisions=changed,
            reviewed_by="reviewer",
            review_notes="exact notes",
            confirm_physical_device_review_complete=True,
            reuse_existing=True,
        )
