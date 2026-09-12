from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_hair_deformation_review as review


JOB_ID = "hfpreview-" + ("a" * 32)
REVISION = "b" * 40
PACKAGE_SHA = "c" * 64
AVATAR_SHA = "d" * 64


class FloatOnce(float):
    def __new__(cls, value: float):
        instance = super().__new__(cls, value)
        instance.calls = 0
        return instance

    def __float__(self) -> float:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("metric was converted more than once")
        return super().__float__()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, allow_nan=True, sort_keys=True) + "\n", encoding="utf-8")


def _machine_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    probe_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    root = (tmp_path / "preview").resolve()
    output = (root / "output").resolve()
    output.mkdir(parents=True)

    preview = {
        "status": "succeeded",
        "job_id": JOB_ID,
        "person_id": "person-1",
        "body_revision": "body-r1",
        "canonical_body_id": "body-1",
        "bodyrig_revision": REVISION,
        "candidate_package_sha256": PACKAGE_SHA,
        "review_vrm_sha256": AVATAR_SHA,
    }
    component_review = {
        "review_outcome": {"hair": "visual-pass-deformation-review-required"},
        "promotion_eligibility": {"hair": False},
        "review_vrm_sha256": AVATAR_SHA,
    }
    component_path = root / "component-review.json"
    _write_json(component_path, component_review)

    monkeypatch.setattr(review.preview_jobs, "get", lambda job_id: preview)
    monkeypatch.setattr(review, "read_component_review", lambda job_id: component_review)
    monkeypatch.setattr(review, "_preview_root", lambda job_id: root)
    monkeypatch.setattr(
        review,
        "component_review_path",
        lambda job_id, *, review_vrm_sha256: component_path,
    )

    _write_json(root / "job.json", {"preview_output": str(output)})

    probe: dict[str, object] = {
        "format": "bodyrig-hair-deformation-probe",
        "version": 1,
        "bodyrig_revision": REVISION,
        "platform": "windows-unity-univrm",
        "package_sha256": PACKAGE_SHA,
        "avatar_sha256": AVATAR_SHA,
        "sequence_revision": "source-hair-head-turn-v1",
        "hair_node": "BodyRigSourceHairReview",
        "hair_mesh": "BodyRigSourceHairReviewMesh",
        "skinned_mesh_renderer_found": True,
        "head_bone_resolved": True,
        "head_bone_bound": True,
        "vertex_motion_observed": True,
        "restored_neutral": True,
        "complete": True,
        "human_review_required": True,
        "comparison_only": True,
        "hair_component_authority": False,
        "production_activation": False,
        "observed_head_turn_degrees": 18.2,
        "vertex_motion_rms_m": 0.00025,
        "vertex_motion_max_m": 0.001,
        "restoration_rms_m": 0.0,
        "restoration_max_m": 0.0,
    }
    if probe_overrides:
        probe.update(probe_overrides)

    probe_path = output / "hair-deformation-probe.json"
    _write_json(probe_path, probe)
    probe_sha = hashlib.sha256(probe_path.read_bytes()).hexdigest()

    comparison = {
        "authority": "source-hair-eye-review-runtime",
        "hair_deformation_probe_sha256": probe_sha,
        "hair_deformation_machine_pass": True,
        "hair_deformation_human_review_required": True,
        "physical_acceptance_authority": False,
        "production_activation": False,
    }
    _write_json(output / "comparison-authority.json", comparison)

    return review._machine_authority(JOB_ID)


def test_machine_probe_rejects_boolean_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(
        review.HighFidelityHairDeformationReviewError,
        match="hair deformation machine probe is stale, incomplete or activating",
    ):
        _machine_fixture(tmp_path, monkeypatch, probe_overrides={"version": True})


def test_machine_probe_accepts_numeric_float_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authority = _machine_fixture(tmp_path, monkeypatch, probe_overrides={"version": 1.0})

    assert authority["machine_metrics"] == {
        "observed_head_turn_degrees": 18.2,
        "vertex_motion_rms_m": 0.00025,
        "vertex_motion_max_m": 0.001,
        "restoration_rms_m": 0.0,
        "restoration_max_m": 0.0,
    }


@pytest.mark.parametrize(
    "value",
    [
        10**400,
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_machine_probe_rejects_unrepresentable_or_nonfinite_metric(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: object,
) -> None:
    with pytest.raises(
        review.HighFidelityHairDeformationReviewError,
        match="hair deformation metric restoration_rms_m is invalid",
    ):
        _machine_fixture(tmp_path, monkeypatch, probe_overrides={"restoration_rms_m": value})


def test_metric_conversion_happens_exactly_once() -> None:
    value = FloatOnce(0.00025)

    result = review._metric(
        value,
        field="restoration_rms_m",
        minimum=0.0,
        maximum=0.00025,
    )

    assert result == pytest.approx(0.00025)
    assert value.calls == 1


def _review_receipt_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, dict[str, object]]:
    authority = {
        "preview": {
            "job_id": JOB_ID,
            "person_id": "person-1",
            "body_revision": "body-r1",
            "canonical_body_id": "body-1",
            "bodyrig_revision": REVISION,
            "candidate_package_sha256": PACKAGE_SHA,
            "review_vrm_sha256": AVATAR_SHA,
        },
        "component_review_sha256": "e" * 64,
        "comparison_authority_sha256": "f" * 64,
        "hair_deformation_probe_sha256": "1" * 64,
        "machine_metrics": {
            "observed_head_turn_degrees": 18.2,
            "vertex_motion_rms_m": 0.00025,
            "vertex_motion_max_m": 0.001,
            "restoration_rms_m": 0.0,
            "restoration_max_m": 0.0,
        },
    }
    receipt_path = tmp_path / "hair-review.json"
    monkeypatch.setattr(review, "_machine_authority", lambda preview_job_id: authority)
    monkeypatch.setattr(
        review,
        "review_path",
        lambda preview_job_id, *, hair_probe_sha256: receipt_path,
    )
    receipt = review.write_review(
        JOB_ID,
        bodyrig_revision=REVISION,
        checklist={field: True for field in review.CHECKLIST_FIELDS},
        quality_note="Hair deformation reviewed at canonical head-turn sequence.",
    )
    return receipt_path, receipt


def test_review_receipt_rejects_boolean_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt_path, receipt = _review_receipt_fixture(tmp_path, monkeypatch)
    receipt["version"] = True
    _write_json(receipt_path, receipt)

    with pytest.raises(
        review.HighFidelityHairDeformationReviewError,
        match="hair deformation review format/version/policy mismatch",
    ):
        review.read_review(JOB_ID)


def test_review_receipt_accepts_numeric_float_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt_path, receipt = _review_receipt_fixture(tmp_path, monkeypatch)
    receipt["version"] = 1.0
    _write_json(receipt_path, receipt)

    verified = review.read_review(JOB_ID)

    assert verified["version"] == 1.0
    assert verified["hair_promotion_eligible"] is True
    assert verified["production_activation"] is False
