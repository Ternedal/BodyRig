from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.body_feedback import propose_bodyprint_changes
from bodyrig.bodyprint_adjustment import (
    BodyprintAdjustmentEvidenceError,
    apply_adjustment_to_bodyprint,
    bind_request_to_proof,
    build_adjustment_request,
    effective_bodyprint_from_files,
    load_adjustment_evidence,
)


def _proof() -> dict:
    return {
        "format": "bodyrig-recovery-proof",
        "version": 1,
        "source_count": 1,
        "adapter": "4d-humans-hmr2-phalp",
        "revision": "test-revision",
        "track_id": "track-1",
        "observed_frames": 12,
        "bodyprint": {
            "format": "modelrig-bodyprint",
            "version": 1,
            "shape": {
                "shoulder_to_height": 0.25,
                "hip_to_height": 0.20,
                "arm_to_height": 0.35,
                "leg_to_height": 0.48,
            },
            "motion": {
                "energy": 0.50,
                "gesture_amplitude": 0.40,
                "head_motion": 0.30,
            },
        },
    }


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_adjustment_is_bound_to_exact_raw_recovery_proof(tmp_path: Path) -> None:
    proof_path = tmp_path / "proof.json"
    _write(proof_path, _proof())
    request = build_adjustment_request("Armene er for lange og der skal være mere energi")
    evidence = bind_request_to_proof(request, proof_path=proof_path)

    evidence_path = tmp_path / "adjustment.json"
    _write(evidence_path, evidence)
    loaded = load_adjustment_evidence(evidence_path, proof_path=proof_path)
    assert loaded == evidence

    tampered = _proof()
    tampered["observed_frames"] = 13
    _write(proof_path, tampered)
    with pytest.raises(BodyprintAdjustmentEvidenceError, match="different recovery proof"):
        load_adjustment_evidence(evidence_path, proof_path=proof_path)


def test_effective_bodyprint_changes_only_reviewed_fields(tmp_path: Path) -> None:
    proof = _proof()
    proof_path = tmp_path / "proof.json"
    _write(proof_path, proof)
    proposals = propose_bodyprint_changes("Armene er for lange og der skal være mere energi")
    request = build_adjustment_request(
        "Armene er for lange og der skal være mere energi",
        changes=proposals,
    )
    evidence = bind_request_to_proof(request, proof_path=proof_path)
    evidence_path = tmp_path / "adjustment.json"
    _write(evidence_path, evidence)

    effective = effective_bodyprint_from_files(
        proof_path=proof_path,
        adjustment_path=evidence_path,
    )
    assert effective["shape"]["arm_to_height"] == pytest.approx(0.335)
    assert effective["motion"]["energy"] == pytest.approx(0.58)
    assert effective["shape"]["shoulder_to_height"] == 0.25
    assert proof["bodyprint"]["shape"]["arm_to_height"] == 0.35


def test_reviewed_subset_of_generated_proposal_is_allowed() -> None:
    feedback = "Armene er for lange og der skal være mere energi"
    proposals = propose_bodyprint_changes(feedback)
    request = build_adjustment_request(feedback, changes=[proposals[0]])
    assert request["changes"] == [proposals[0].to_json()]


def test_explicit_changes_must_match_same_feedback_proposal() -> None:
    with pytest.raises(BodyprintAdjustmentEvidenceError, match="exact subset"):
        build_adjustment_request(
            "Armene skal være kortere",
            changes=[
                {
                    "field": "shape.shoulder_to_height",
                    "delta": 0.010,
                    "reason": "shoulders should be broader",
                }
            ],
        )


def test_explicit_change_cannot_modify_generated_delta_or_reason() -> None:
    with pytest.raises(BodyprintAdjustmentEvidenceError, match="exact subset"):
        build_adjustment_request(
            "Armene skal være kortere",
            changes=[
                {
                    "field": "shape.arm_to_height",
                    "delta": -0.010,
                    "reason": "arm length should be reduced",
                }
            ],
        )


def test_height_scale_uses_neutral_one_when_source_bodyprint_has_no_height_scale(tmp_path: Path) -> None:
    proof = _proof()
    proof_path = tmp_path / "proof.json"
    _write(proof_path, proof)
    request = build_adjustment_request("Kroppen skal være højere")
    evidence = bind_request_to_proof(request, proof_path=proof_path)
    effective = apply_adjustment_to_bodyprint(proof["bodyprint"], evidence)
    assert effective["shape"]["height_scale"] == pytest.approx(1.03)
    assert "height_scale" not in proof["bodyprint"]["shape"]


def test_explicit_unbounded_delta_is_rejected() -> None:
    with pytest.raises(BodyprintAdjustmentEvidenceError, match="bounded V1 limit"):
        build_adjustment_request(
            "Armene skal være kortere",
            changes=[
                {
                    "field": "shape.arm_to_height",
                    "delta": -0.25,
                    "reason": "too much",
                }
            ],
        )


def test_missing_source_field_is_not_silently_invented(tmp_path: Path) -> None:
    proof = _proof()
    del proof["bodyprint"]["motion"]["gesture_amplitude"]
    proof_path = tmp_path / "proof.json"
    _write(proof_path, proof)
    request = build_adjustment_request("Mere gestik")
    evidence = bind_request_to_proof(request, proof_path=proof_path)
    with pytest.raises(BodyprintAdjustmentEvidenceError, match="not present"):
        apply_adjustment_to_bodyprint(proof["bodyprint"], evidence)
