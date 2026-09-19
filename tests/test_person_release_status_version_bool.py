from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig import person_release_status as release


def _quality_review() -> dict[str, object]:
    return {
        "revision": "bodyrig-human-quality-v1",
        **{field: True for field in release.QUALITY_REVIEW_BOOLEAN_FIELDS},
    }


def _probe(*, version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-renderer-probe",
        "version": version,
        "platform": "windows-unity-univrm",
        "unity_platform": "WindowsPlayer",
        "device_model": "Windows reference rig",
        "active_renderer": {},
    }


def _attestation(*, version: object = 1) -> dict[str, object]:
    return {
        "format": "bodyrig-renderer-acceptance",
        "version": version,
        "platform": "windows-unity-univrm",
        "result": "pass",
        "attestation": "operator-supplied",
        "machine_probe": True,
        "deformation_probe": True,
        "production_activation": False,
        "quality_review": _quality_review(),
    }


@pytest.mark.parametrize("value", [True, False])
def test_release_v1_helper_rejects_boolean(value: bool) -> None:
    assert release._is_v1(value) is False


def test_release_v1_helper_accepts_numeric_one() -> None:
    assert release._is_v1(1) is True
    assert release._is_v1(1.0) is True


@pytest.mark.parametrize(
    ("probe_version", "attestation_version", "message"),
    [
        (True, 1, "renderer machine probe format/platform mismatch"),
        (1, True, "renderer attestation format/version mismatch"),
    ],
)
def test_platform_attestation_rejects_boolean_versions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_version: object,
    attestation_version: object,
    message: str,
) -> None:
    probe_path = tmp_path / "probe.json"
    attestation_path = tmp_path / "attestation.json"
    monkeypatch.setattr(
        release,
        "_platform_paths",
        lambda *_args, **_kwargs: (probe_path, attestation_path),
    )

    def read_json(path: Path, _label: str) -> dict[str, object]:
        if path == probe_path:
            return _probe(version=probe_version)
        return _attestation(version=attestation_version)

    monkeypatch.setattr(release, "_read_json", read_json)

    with pytest.raises(release.PersonReleaseStatusError, match=message):
        release._strict_platform_attestation(
            tmp_path,
            prefix="windows-unity-univrm",
            platform="windows-unity-univrm",
        )


def test_boolean_v1_ui_job_is_not_release_origin_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release,
        "_registered_fidelity_status",
        lambda **_kwargs: {
            "state": "ready",
            "high_fidelity_ready": True,
            "production_ready": True,
        },
    )
    job = {
        "format": "bodyrig-ui-job",
        "version": True,
        "kind": "body-build",
        "person_id": "person-" + "a" * 32,
        "body_revision": "body-r0001",
    }

    result = release.inspect_candidate_release_status(
        [job],
        person_id="person-" + "a" * 32,
        body_revision="body-r0001",
        body_id="bodyid-" + "b" * 24,
        package_sha256="c" * 64,
    )

    assert result["state"] == "unavailable"
    assert result["production_activation"] is False
