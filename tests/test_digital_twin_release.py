from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_release as m6
from bodyrig.digital_twin_status import _final_release_gate

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


def test_m6_structure_is_the_only_activating_authority() -> None:
    chain = _chain()
    authority = m6._authority_from_chain(chain)
    validated = m6.validate_release_authority_structure(
        authority,
        composition_authority=chain["composition"],
        platform_acceptance_status=chain["m5_status"],
        body_release_status=_body_release(),
    )
    assert validated["digital_twin_ready"] is True
    assert validated["production_activation"] is True
    assert validated["state"] == "released"
    assert validated["release_id"].startswith("dtrelease-")


def test_digital_twin_status_final_gate_accepts_only_canonical_m6() -> None:
    chain = _chain()
    authority = m6._authority_from_chain(chain)
    gate = _final_release_gate(
        authority,
        composition_authority=chain["composition"],
        platform_acceptance_status=chain["m5_status"],
        body_release_status=_body_release(),
    )
    assert gate["ready"] is True
    assert gate["state"] == "complete"
    assert gate["release_id"] == authority["release_id"]

    forged = dict(authority)
    forged["windows_realization_sha256"] = "f" * 64
    blocked = _final_release_gate(
        forged,
        composition_authority=chain["composition"],
        platform_acceptance_status=chain["m5_status"],
        body_release_status=_body_release(),
    )
    assert blocked["ready"] is False
    assert blocked["state"] == "blocked"


def test_m6_rejects_activation_without_complete_m5() -> None:
    chain = _chain()
    authority = m6._authority_from_chain(chain)
    m5_status = copy.deepcopy(chain["m5_status"])
    m5_status["m5_ready"] = False
    with pytest.raises(m6.DigitalTwinReleaseError, match="M5 platform status"):
        m6.validate_release_authority_structure(
            authority,
            composition_authority=chain["composition"],
            platform_acceptance_status=m5_status,
            body_release_status=_body_release(),
        )


def test_m6_rejects_non_activating_or_forged_state() -> None:
    chain = _chain()
    authority = m6._authority_from_chain(chain)
    authority["production_activation"] = False
    with pytest.raises(m6.DigitalTwinReleaseError, match="activating full digital-twin release"):
        m6.validate_release_authority_structure(
            authority,
            composition_authority=chain["composition"],
            platform_acceptance_status=chain["m5_status"],
            body_release_status=_body_release(),
        )


def test_m6_bundle_is_create_only_and_frozen_tamper_revokes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    chain = _chain()
    monkeypatch.setattr(m6, "_chain_evidence", lambda **kwargs: chain)
    composition_dir = tmp_path / "composition"
    acceptance_dir = tmp_path / "acceptance"
    composition_dir.mkdir()
    acceptance_dir.mkdir()

    authority = m6.write_release(
        tmp_path / "library",
        composition_authority_dir=composition_dir,
        acceptance_dir=acceptance_dir,
        bodyrig_revision=REVISION,
    )
    assert authority["digital_twin_ready"] is True
    assert authority["production_activation"] is True

    with pytest.raises(m6.DigitalTwinReleaseError, match="already exists"):
        m6.write_release(
            tmp_path / "library",
            composition_authority_dir=composition_dir,
            acceptance_dir=acceptance_dir,
            bodyrig_revision=REVISION,
        )

    directory = m6.release_dir(
        tmp_path / "library",
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        release_id=authority["release_id"],
    )
    realization = directory / "windows-realization.json"
    realization.write_bytes(realization.read_bytes() + b"\n")
    with pytest.raises(m6.DigitalTwinReleaseError, match="frozen M6 evidence bytes were modified"):
        m6.read_release(
            tmp_path / "library",
            person_id=PERSON_ID,
            person_revision=PERSON_REVISION,
            release_id=authority["release_id"],
            composition_authority_dir=composition_dir,
            acceptance_dir=acceptance_dir,
        )


def test_m6_readback_revokes_on_live_lineage_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    chain = _chain()
    current = {"value": chain}
    monkeypatch.setattr(m6, "_chain_evidence", lambda **kwargs: current["value"])
    composition_dir = tmp_path / "composition"
    acceptance_dir = tmp_path / "acceptance"
    composition_dir.mkdir()
    acceptance_dir.mkdir()

    authority = m6.write_release(
        tmp_path / "library",
        composition_authority_dir=composition_dir,
        acceptance_dir=acceptance_dir,
        bodyrig_revision=REVISION,
    )
    drifted = copy.deepcopy(chain)
    drifted["windows"]["realization_raw"] = b'{"platform":"windows-unity-univrm","changed":true}\n'
    drifted_sha = hashlib.sha256(drifted["windows"]["realization_raw"]).hexdigest()
    drifted["m5_status"]["platforms"]["windows-unity-univrm"]["realization_sha256"] = drifted_sha
    current["value"] = drifted

    with pytest.raises(m6.DigitalTwinReleaseError, match="live M4/M5/body evidence"):
        m6.read_release(
            tmp_path / "library",
            person_id=PERSON_ID,
            person_revision=PERSON_REVISION,
            release_id=authority["release_id"],
            composition_authority_dir=composition_dir,
            acceptance_dir=acceptance_dir,
        )


def test_m6_operator_wrapper_is_exact_checkout_and_physical_chain_bound() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "finalize-digital-twin-release.ps1").read_text(encoding="utf-8")
    assert "[System.Environment]::OSVersion.Platform" in source
    assert "PowerShell 7+" in source
    assert "git -C $script:RepoRoot rev-parse HEAD" in source
    assert "git -C $script:RepoRoot status --porcelain" in source
    assert "bodyrig-release-acceptance.json" in source
    assert "digital-twin-windows-evidence" in source
    assert "digital-twin-quest-evidence" in source
    assert "production_activation -ne $true" in source
    assert "bodyrig.digital_twin_release_cli" in source
