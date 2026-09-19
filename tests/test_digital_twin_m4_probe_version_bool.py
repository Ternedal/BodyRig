from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_platform_acceptance as m5


def _authority_dir(tmp_path: Path) -> Path:
    path = (
        tmp_path
        / "digital-twin-composition-authorities"
        / ("person-" + "a" * 32)
        / "person-r0001"
        / ("dtcomp-" + "b" * 32)
    )
    path.mkdir(parents=True)
    (path / "authority.json").write_text("{}\n", encoding="utf-8")
    return path


def _probe(*, version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-digital-twin-embodiment-probe",
        "version": version,
        "motor_state": {
            "type": "bodyrig-motor-state",
            "version": 2,
            "body_id": "body-test",
            "utterance_id": "bodyrig-m4-embodiment-probe",
            "embodiment": {"status": "complete-observed"},
        },
    }


def test_m4_embodiment_probe_rejects_boolean_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority_dir = _authority_dir(tmp_path)
    (authority_dir / "embodiment-probe.json").write_text(
        json.dumps(_probe(version=True)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        m5,
        "read_composition_authority",
        lambda *_args, **_kwargs: {"body_id": "body-test"},
    )

    with pytest.raises(
        m5.DigitalTwinPlatformAcceptanceError,
        match="M4 embodiment probe format/version is invalid",
    ):
        m5._composition_bundle(
            authority_dir,
            package_path=tmp_path / "body.mrbody",
        )


def test_m4_embodiment_probe_preserves_numeric_float_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority_dir = _authority_dir(tmp_path)
    (authority_dir / "embodiment-probe.json").write_text(
        json.dumps(_probe(version=1.0)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        m5,
        "read_composition_authority",
        lambda *_args, **_kwargs: {"body_id": "body-test"},
    )

    authority, authority_raw, probe, probe_raw = m5._composition_bundle(
        authority_dir,
        package_path=tmp_path / "body.mrbody",
    )

    assert authority["body_id"] == "body-test"
    assert authority_raw == b"{}\n"
    assert probe["version"] == 1.0
    assert probe_raw
