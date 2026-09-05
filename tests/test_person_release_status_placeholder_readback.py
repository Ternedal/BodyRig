from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.person_release_status import PersonReleaseStatusError, inspect_candidate_release_status

PERSON_ID = "person-" + "1" * 32
BODY_REVISION = "body-r0001"
BODY_ID = "bodyid-" + "2" * 24
PACKAGE_SHA = "3" * 64
BODYRIG_REVISION = "4" * 40
RENDERER_NAME = "BodyRig Reference Renderer"
RENDERER_VERSION = "reference-v1/univrm-0.131.2"
UNITY_VERSION = "6000.3.13f1"
DEFORMATION_REVISION = "humanoid-muscle-sweep-v1"
QUALITY_REVIEW = {
    "revision": "bodyrig-human-quality-v1",
    "full_deformation_sequence_reviewed": True,
    "source_identity_texture_acceptable": True,
    "geometry_proportions_acceptable": True,
    "upper_body_deformation_acceptable": True,
    "lower_body_deformation_acceptable": True,
    "cross_limb_leakage_absent": True,
    "skin_qa_considered": True,
}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _platform(
    acceptance: Path,
    *,
    prefix: str,
    platform: str,
    unity_platform: str,
    device_model: str,
    quality_note: str,
) -> None:
    _write(
        acceptance / f"{prefix}-evidence" / f"{prefix}-probe.json",
        {
            "format": "bodyrig-renderer-probe",
            "version": 1,
            "platform": platform,
            "unity_platform": unity_platform,
            "unity_version": UNITY_VERSION,
            "device_model": device_model,
            "graphics_device": "test-gpu",
            "active_renderer": {"name": RENDERER_NAME, "version": RENDERER_VERSION},
        },
    )
    _write(
        acceptance / f"bodyrig-renderer-acceptance-{prefix}.json",
        {
            "format": "bodyrig-renderer-acceptance",
            "version": 1,
            "platform": platform,
            "result": "pass",
            "attestation": "operator-supplied",
            "machine_probe": True,
            "deformation_probe": True,
            "production_activation": False,
            "renderer_name": RENDERER_NAME,
            "renderer_version": RENDERER_VERSION,
            "unity_platform": unity_platform,
            "unity_version": UNITY_VERSION,
            "graphics_device": "test-gpu",
            "deformation_sequence_revision": DEFORMATION_REVISION,
            "quality_review": dict(QUALITY_REVIEW),
            "quality_note": quality_note,
        },
    )


def test_complete_person_release_rejects_placeholder_renderer_human_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    _write(
        acceptance / "bodyrig-acceptance.json",
        {"package": {"body_id": BODY_ID, "package_sha256": PACKAGE_SHA}},
    )
    _platform(
        acceptance,
        prefix="windows",
        platform="windows-unity-univrm",
        unity_platform="WindowsPlayer",
        device_model="Windows test rig",
        quality_note="<your physical review>",
    )
    _platform(
        acceptance,
        prefix="quest",
        platform="android-quest-class",
        unity_platform="Android",
        device_model="Meta Quest 2",
        quality_note="actual headset review",
    )

    monkeypatch.setattr(
        "bodyrig.person_release_status.inspect_acceptance_dir",
        lambda _: AcceptanceStatus(
            state="complete",
            gate="release",
            acceptance_dir=str(acceptance),
            body_id=BODY_ID,
            bodyrig_revision=BODYRIG_REVISION,
            message="historical complete release",
            next_command=None,
        ),
    )
    monkeypatch.setattr(
        "bodyrig.person_release_status._registered_fidelity_status",
        lambda **_: {
            "high_fidelity_ready": True,
            "human_review": {"passed": True},
        },
    )

    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "kind": "body-build",
        "job_id": "job-test",
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "canonical_body_id": BODY_ID,
        "acceptance_dir": str(acceptance),
        "created_utc": "2026-09-05T12:00:00Z",
        "status": "succeeded",
    }

    with pytest.raises(PersonReleaseStatusError, match="generated placeholder"):
        inspect_candidate_release_status(
            [job],
            person_id=PERSON_ID,
            body_revision=BODY_REVISION,
            body_id=BODY_ID,
            package_sha256=PACKAGE_SHA,
        )
