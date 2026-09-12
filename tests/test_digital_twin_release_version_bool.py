from __future__ import annotations

import hashlib
import json

import pytest

import bodyrig.digital_twin_release as m6


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
REVISION = "a" * 40
PACKAGE_SHA = "1" * 64
BODYPRINT_SHA = "2" * 64
ASSEMBLY_SHA = "3" * 64
AUTHORITY_ID = "dtcomp-0123456789abcdef0123456789abcdef"


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _composition() -> dict:
    return {
        "format": "bodyrig-digital-twin-composition-authority",
        "version": 1,
        "authority_id": AUTHORITY_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyprint_sha256": BODYPRINT_SHA,
        "bodyrig_revision": REVISION,
    }


def _m5_status(windows_sha: str, quest_sha: str) -> dict:
    return {
        "format": "bodyrig-digital-twin-platform-status",
        "version": 1,
        "m5_ready": True,
        "digital_twin_ready": False,
        "production_activation": False,
        "platforms": {
            "windows-unity-univrm": {
                "ready": True,
                "state": "complete",
                "realization_sha256": windows_sha,
            },
            "android-quest-class": {
                "ready": True,
                "state": "complete",
                "realization_sha256": quest_sha,
            },
        },
    }


def _chain() -> dict:
    composition = _composition()
    composition_raw = _canonical(composition) + b"\n"
    gate_raw = b'{"format":"bodyrig-rig-acceptance","version":1}\n'
    physical_release_raw = b'{"format":"bodyrig-release-acceptance","release_gate_pass":true,"production_activation":true}\n'
    windows_input = {"renderer_attestation_sha256": "4" * 64}
    quest_input = {"renderer_attestation_sha256": "5" * 64}
    windows_input_raw = _canonical(windows_input)
    quest_input_raw = _canonical(quest_input)
    windows_realization_raw = b'{"platform":"windows-unity-univrm","production_activation":false}\n'
    quest_realization_raw = b'{"platform":"android-quest-class","production_activation":false}\n'
    windows_sha = hashlib.sha256(windows_realization_raw).hexdigest()
    quest_sha = hashlib.sha256(quest_realization_raw).hexdigest()
    return {
        "composition": composition,
        "composition_raw": composition_raw,
        "m5_status": _m5_status(windows_sha, quest_sha),
        "revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "gate_a_raw": gate_raw,
        "physical_release_raw": physical_release_raw,
        "physical_release": {"release_gate_pass": True, "production_activation": True},
        "windows": {
            "input_raw": windows_input_raw,
            "input": windows_input,
            "realization_raw": windows_realization_raw,
            "realization": {"bodyrig_revision": REVISION, "body_id": BODY_ID, "production_activation": False},
        },
        "quest": {
            "input_raw": quest_input_raw,
            "input": quest_input,
            "realization_raw": quest_realization_raw,
            "realization": {"bodyrig_revision": REVISION, "body_id": BODY_ID, "production_activation": False},
        },
    }


def _body_release() -> dict:
    return {
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "production_ready": True,
        "production_activation": True,
    }


def _validate(chain: dict, authority: dict) -> dict:
    return m6.validate_release_authority_structure(
        authority,
        composition_authority=chain["composition"],
        platform_acceptance_status=chain["m5_status"],
        body_release_status=_body_release(),
    )


def test_m6_rejects_boolean_release_version() -> None:
    chain = _chain()
    authority = m6._authority_from_chain(chain)
    authority["version"] = True

    with pytest.raises(m6.DigitalTwinReleaseError, match="format/version/policy"):
        _validate(chain, authority)


def test_m6_rejects_boolean_m4_composition_version() -> None:
    chain = _chain()
    chain["composition"]["version"] = True
    chain["composition_raw"] = _canonical(chain["composition"]) + b"\n"
    authority = m6._authority_from_chain(chain)

    with pytest.raises(m6.DigitalTwinReleaseError, match="finalized M4 composition authority"):
        _validate(chain, authority)


def test_m6_rejects_boolean_m5_platform_status_version() -> None:
    chain = _chain()
    authority = m6._authority_from_chain(chain)
    chain["m5_status"]["version"] = True

    with pytest.raises(m6.DigitalTwinReleaseError, match="canonical M5 platform status"):
        _validate(chain, authority)


def test_m6_preserves_numeric_float_v1_compatibility_across_full_structure() -> None:
    chain = _chain()
    chain["composition"]["version"] = 1.0
    chain["composition_raw"] = _canonical(chain["composition"]) + b"\n"
    chain["m5_status"]["version"] = 1.0
    authority = m6._authority_from_chain(chain)
    authority["version"] = 1.0

    validated = _validate(chain, authority)

    assert validated["version"] == 1.0
    assert validated["state"] == "released"
    assert validated["digital_twin_ready"] is True
    assert validated["production_activation"] is True
    assert validated["release_id"] == authority["release_id"]
