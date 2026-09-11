from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.high_fidelity_release_gate as release_gate


BODY_ID = "bodyid-" + "7" * 24


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provenance(*, visual_revision: str = "identity-v1", fitting_adapter: str = "sith-smplx-vrm") -> dict:
    return {
        "source": {"kind": "user-supplied-local-media", "count": 3},
        "pipeline": [
            {"stage": "body-recovery", "adapter": "recoverer", "revision": "recovery-v1"},
            {"stage": "visual-identity-capture", "adapter": "identity", "revision": visual_revision},
            {"stage": "avatar-fitting", "adapter": fitting_adapter, "revision": "1"},
        ],
    }


def _movement_identity() -> dict:
    return {
        "movement_observed_frames": 60,
        "movement_observed_seconds": 4.5,
        "gait_step_events": 7,
        "idle_observed_seconds": 0.9,
        "posture_torso_lean_degrees": 5.1,
        "posture_torso_forward_lean_degrees": 4.6,
        "posture_torso_right_lean_degrees": -1.1,
        "posture_shoulder_tilt_degrees": 1.2,
        "posture_shoulder_roll_degrees": -1.2,
        "posture_hip_tilt_degrees": 0.8,
        "posture_hip_roll_degrees": -0.8,
        "posture_head_offset_to_height": 0.04,
        "posture_head_forward_offset_to_height": 0.035,
        "posture_head_right_offset_to_height": 0.017,
        "walk_cadence_spm": 114.0,
        "stride_length_to_height": 0.33,
        "stance_width_to_height": 0.14,
        "vertical_bounce_to_height": 0.024,
        "arm_swing_to_height": 0.19,
        "arm_swing_asymmetry": 0.07,
        "turn_speed": 0.21,
        "turn_speed_degrees_per_second": 37.8,
        "transition_intensity": 0.28,
        "idle_sway_to_height": 0.011,
    }


def _bodyprint(*, shoulder: float = 0.24, omit_movement_field: str | None = None) -> dict:
    motion = {"energy": 0.5, "gesture_amplitude": 0.3, **_movement_identity()}
    if omit_movement_field is not None:
        motion.pop(omit_movement_field)
    return {
        "shape": {
            "shoulder_to_height": shoulder,
            "hip_to_height": 0.18,
            "arm_to_height": 0.42,
            "leg_to_height": 0.53,
        },
        "motion": motion,
    }


def _source_report() -> dict:
    return {
        "bodyrig_checkout_clean": True,
        "source_count": 3,
        "recovery": {
            "adapter": "recoverer",
            "revision": "recovery-v1",
            "track_id": "track-1",
            "observed_frames": 60,
        },
        "checks": {name: True for name in release_gate.CANONICAL_RELEASE_CHECKS},
    }


def _arrange(monkeypatch, tmp_path: Path, *, source_bodyprint: dict | None = None, promoted_bodyprint: dict | None = None, promoted_provenance: dict | None = None):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_package = source_dir / f"{BODY_ID}.mrbody"
    promoted_package = tmp_path / "promoted.mrbody"
    source_package.write_bytes(b"source-package")
    promoted_package.write_bytes(b"promoted-package")

    source_value = source_bodyprint or _bodyprint()
    promoted_value = promoted_bodyprint or source_value
    source_validated = SimpleNamespace(
        manifest={"id": BODY_ID},
        bodyprint=source_value,
        provenance=_provenance(),
    )
    promoted_validated = SimpleNamespace(
        manifest={"id": BODY_ID},
        bodyprint=promoted_value,
        provenance=promoted_provenance or _provenance(),
    )

    def validate(path: str | Path):
        resolved = Path(path).resolve()
        if resolved == source_package.resolve():
            return source_validated
        if resolved == promoted_package.resolve():
            return promoted_validated
        raise AssertionError(f"unexpected package path: {resolved}")

    monkeypatch.setattr(release_gate, "validate_package", validate)
    monkeypatch.setattr(release_gate, "_validate_vrm", lambda _path: "1.0")
    gate = SimpleNamespace(body_id=BODY_ID, package_hash=_sha(source_package))
    return source_dir, promoted_package, gate


def test_promoted_release_lineage_reproves_final_package(monkeypatch, tmp_path: Path) -> None:
    source_dir, promoted, gate = _arrange(monkeypatch, tmp_path)

    result = release_gate.validate_promoted_release_lineage(
        promoted,
        source_dir=source_dir,
        source_gate=gate,
        source_report=_source_report(),
    )

    assert result["source_count"] == 3
    assert result["recovery"]["observed_frames"] == 60
    assert result["vrm_spec_version"] == "1.0"
    assert result["source_bodyprint_sha256"] == result["bodyprint_sha256"]
    assert result["avatar_fitting_provenance"]["adapter"] == "sith-smplx-vrm"
    assert all(result["checks"][name] is True for name in release_gate.CANONICAL_RELEASE_CHECKS)


def test_promoted_release_lineage_rejects_bodyprint_drift(monkeypatch, tmp_path: Path) -> None:
    source_dir, promoted, gate = _arrange(monkeypatch, tmp_path, promoted_bodyprint=_bodyprint(shoulder=0.31))

    with pytest.raises(release_gate.HighFidelityReleaseGateError, match="BodyPrint differs"):
        release_gate.validate_promoted_release_lineage(
            promoted,
            source_dir=source_dir,
            source_gate=gate,
            source_report=_source_report(),
        )


def test_promoted_release_rejects_generic_motion_without_gait_identity(monkeypatch, tmp_path: Path) -> None:
    incomplete = _bodyprint(omit_movement_field="walk_cadence_spm")
    source_dir, promoted, gate = _arrange(
        monkeypatch,
        tmp_path,
        source_bodyprint=incomplete,
        promoted_bodyprint=incomplete,
    )

    with pytest.raises(release_gate.HighFidelityReleaseGateError, match="Movement Identity"):
        release_gate.validate_promoted_release_lineage(
            promoted,
            source_dir=source_dir,
            source_gate=gate,
            source_report=_source_report(),
        )


def test_promoted_release_rejects_magnitude_only_posture_identity(monkeypatch, tmp_path: Path) -> None:
    incomplete = _bodyprint(omit_movement_field="posture_torso_forward_lean_degrees")
    source_dir, promoted, gate = _arrange(
        monkeypatch,
        tmp_path,
        source_bodyprint=incomplete,
        promoted_bodyprint=incomplete,
    )

    with pytest.raises(release_gate.HighFidelityReleaseGateError, match="Movement Identity"):
        release_gate.validate_promoted_release_lineage(
            promoted,
            source_dir=source_dir,
            source_gate=gate,
            source_report=_source_report(),
        )


def test_promoted_release_lineage_rejects_visual_provenance_drift(monkeypatch, tmp_path: Path) -> None:
    source_dir, promoted, gate = _arrange(
        monkeypatch,
        tmp_path,
        promoted_provenance=_provenance(visual_revision="different-identity"),
    )

    with pytest.raises(release_gate.HighFidelityReleaseGateError, match="visual-identity provenance differs"):
        release_gate.validate_promoted_release_lineage(
            promoted,
            source_dir=source_dir,
            source_gate=gate,
            source_report=_source_report(),
        )
