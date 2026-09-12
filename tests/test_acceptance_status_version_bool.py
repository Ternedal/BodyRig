from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.acceptance_status import (
    AcceptanceStatusError,
    GateAInfo,
    PlatformPaths,
    _session_status,
    _validate_attestation,
    _validate_deformation,
    _validate_gate_a,
    _validate_probe,
    _validate_release_artifact,
)

REVISION = "a" * 40
BODY_ID = "performer-123"
PACKAGE_HASH = "b" * 64
RUNTIME_HASH = "c" * 64


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def _gate(tmp_path: Path) -> GateAInfo:
    return GateAInfo(
        path=tmp_path / "bodyrig-acceptance.json",
        body_id=BODY_ID,
        revision=REVISION,
        package_hash=PACKAGE_HASH,
        runtime_hash=RUNTIME_HASH,
    )


def _platform_paths(tmp_path: Path) -> PlatformPaths:
    return PlatformPaths(
        probe=tmp_path / "probe.json",
        deformation=tmp_path / "deformation.json",
        attestation=tmp_path / "attestation.json",
        layout="dedicated",
    )


def _release(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-release-acceptance",
        "version": version,
        "completed_at": "",
        "bodyrig_revision": REVISION,
        "automated_acceptance": {},
        "renderer_acceptance": {},
        "release_gate_pass": True,
        "production_activation": True,
    }


def test_session_status_rejects_boolean_v1_version(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "session.json",
        {"format": "bodyrig-physical-clone-session", "version": True},
    )

    with pytest.raises(AcceptanceStatusError, match="Unsupported physical clone session format/version"):
        _session_status(path)


def test_session_status_accepts_numeric_float_v1_discriminator(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "session.json",
        {"format": "bodyrig-physical-clone-session", "version": 1.0},
    )

    with pytest.raises(AcceptanceStatusError, match="session.bodyrig_revision is not a canonical"):
        _session_status(path)


def test_gate_a_rejects_boolean_v1_version(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "bodyrig-acceptance.json",
        {"format": "bodyrig-rig-acceptance", "version": True},
    )

    with pytest.raises(AcceptanceStatusError, match="Unsupported Gate A acceptance format/version"):
        _validate_gate_a(path)


def test_gate_a_accepts_numeric_float_v1_discriminator(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "bodyrig-acceptance.json",
        {
            "format": "bodyrig-rig-acceptance",
            "version": 1.0,
            "automated_pass": False,
            "production_activation": False,
        },
    )

    with pytest.raises(AcceptanceStatusError, match="not a valid non-activating automated PASS"):
        _validate_gate_a(path)


def test_renderer_probe_rejects_boolean_v1_version(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "probe.json",
        {
            "format": "bodyrig-renderer-probe",
            "version": True,
            "platform": "windows-unity-univrm",
        },
    )

    with pytest.raises(AcceptanceStatusError, match="Invalid renderer machine probe"):
        _validate_probe(path, platform="windows-unity-univrm", gate=_gate(tmp_path))


def test_renderer_probe_accepts_numeric_float_v1_discriminator(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "probe.json",
        {
            "format": "bodyrig-renderer-probe",
            "version": 1.0,
            "platform": "windows-unity-univrm",
        },
    )

    with pytest.raises(AcceptanceStatusError, match="probe.bodyrig_revision is not a canonical"):
        _validate_probe(path, platform="windows-unity-univrm", gate=_gate(tmp_path))


def test_deformation_probe_rejects_boolean_v1_version(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "deformation.json",
        {
            "format": "bodyrig-deformation-probe",
            "version": True,
            "platform": "windows-unity-univrm",
        },
    )

    with pytest.raises(AcceptanceStatusError, match="Invalid deformation probe"):
        _validate_deformation(
            path,
            platform="windows-unity-univrm",
            probe={},
            gate=_gate(tmp_path),
        )


def test_deformation_probe_accepts_numeric_float_v1_discriminator(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "deformation.json",
        {
            "format": "bodyrig-deformation-probe",
            "version": 1.0,
            "platform": "windows-unity-univrm",
        },
    )

    with pytest.raises(AcceptanceStatusError, match="deformation.bodyrig_revision is not a canonical"):
        _validate_deformation(
            path,
            platform="windows-unity-univrm",
            probe={},
            gate=_gate(tmp_path),
        )


def test_renderer_attestation_rejects_boolean_v1_version(tmp_path: Path) -> None:
    paths = _platform_paths(tmp_path)
    _write(
        paths.attestation,
        {"format": "bodyrig-renderer-acceptance", "version": True},
    )

    with pytest.raises(AcceptanceStatusError, match="Invalid renderer attestation"):
        _validate_attestation(
            paths.attestation,
            platform="windows-unity-univrm",
            gate=_gate(tmp_path),
            paths=paths,
        )


def test_renderer_attestation_accepts_numeric_float_v1_discriminator(tmp_path: Path) -> None:
    paths = _platform_paths(tmp_path)
    _write(
        paths.attestation,
        {
            "format": "bodyrig-renderer-acceptance",
            "version": 1.0,
            "platform": "wrong-platform",
            "result": "pass",
        },
    )

    with pytest.raises(AcceptanceStatusError, match="not a PASS for windows-unity-univrm"):
        _validate_attestation(
            paths.attestation,
            platform="windows-unity-univrm",
            gate=_gate(tmp_path),
            paths=paths,
        )


def test_final_release_rejects_boolean_v1_version(tmp_path: Path) -> None:
    path = _write(tmp_path / "bodyrig-release-acceptance.json", _release(True))
    paths = _platform_paths(tmp_path)

    with pytest.raises(AcceptanceStatusError, match="Final release acceptance format/version is invalid"):
        _validate_release_artifact(
            path,
            acceptance_dir=tmp_path,
            gate=_gate(tmp_path),
            windows=paths,
            quest=paths,
        )


def test_final_release_accepts_numeric_float_v1_discriminator(tmp_path: Path) -> None:
    path = _write(tmp_path / "bodyrig-release-acceptance.json", _release(1.0))
    paths = _platform_paths(tmp_path)

    with pytest.raises(AcceptanceStatusError, match="Final release acceptance has no completed_at timestamp"):
        _validate_release_artifact(
            path,
            acceptance_dir=tmp_path,
            gate=_gate(tmp_path),
            windows=paths,
            quest=paths,
        )
