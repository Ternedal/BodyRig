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


def _bodyprint(*, shoulder: float = 0.24) -> dict:
    return {
        "shape": {
            "shoulder_to_height": shoulder,
            "hip_to_height": 0.18,
            "arm_to_height": 0.42,
            "leg_to_height": 0.53,
        },
        "motion": {"energy": 0.5, "gesture_amplitude": 0.3},
    }


def _source_report() -> dict:
    return {
        "bodyrig_checkout_clean": True,
        "source_count": 3,
        "recovery": {
            "adapter": "recoverer",
            "revision": "recovery-v1",
            "track_id": "track-1",
            "observed_frames": 4,
        },
        "checks": {name: True for name in release_gate.CANONICAL_RELEASE_CHECKS},
    }


def _arrange(monkeypatch, tmp_path: Path, *, promoted_bodyprint: dict | None = None, promoted_provenance: dict | None = None):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_package = source_dir / f"{BODY_ID}.mrbody"
    promoted_package = tmp_path / "promoted.mrbody"
    source_package.write_bytes(b"source-package")
    promoted_package.write_bytes(b"promoted-package")

    source_validated = SimpleNamespace(
        manifest={"id": BODY_ID},
        bodyprint=_bodyprint(),
        provenance=_provenance(),
    )
    promoted_validated = SimpleNamespace(
        manifest={"id": BODY_ID},
        bodyprint=promoted_bodyprint or _bodyprint(),
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
    assert result["recovery"]["observed_frames"] == 4
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


def test_promoted_release_lineage_rejects_noncanonical_fitter(monkeypatch, tmp_path: Path) -> None:
    source_dir, promoted, gate = _arrange(
        monkeypatch,
        tmp_path,
        promoted_provenance=_provenance(fitting_adapter="other-fitter"),
    )

    with pytest.raises(release_gate.HighFidelityReleaseGateError, match="promoted package lacks canonical"):
        release_gate.validate_promoted_release_lineage(
            promoted,
            source_dir=source_dir,
            source_gate=gate,
            source_report=_source_report(),
        )


def test_release_check_names_remain_aligned_with_canonical_completion_script() -> None:
    root = Path(__file__).resolve().parents[1]
    completion = (root / "complete-acceptance.ps1").read_text(encoding="utf-8")
    physical = (root / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")

    for name in release_gate.CANONICAL_RELEASE_CHECKS:
        assert f"'{name}'" in completion
    assert "_assert_release_compatible_gate_report" in physical
    assert '"recovery": dict(release_lineage["recovery"])' in physical
    assert '"vrm_spec_version": release_lineage["vrm_spec_version"]' in physical