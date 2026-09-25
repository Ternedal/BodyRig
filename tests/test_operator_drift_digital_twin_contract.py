from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_control_plane_ui as twin


PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-test"
PACKAGE_SHA = "a" * 64
BODYRIG_REVISION = "b" * 40


def _profile(*, active: bool = True) -> dict:
    return {
        "person_id": PERSON_ID,
        "active_person_revision": PERSON_REVISION if active else None,
        "person_revisions": [
            {
                "revision_id": PERSON_REVISION,
                "body_revision": BODY_REVISION,
                "voice_revision": "voice-r0001",
                "personality_revision": "personality-r0001",
            }
        ],
        "body_revisions": [
            {
                "revision_id": BODY_REVISION,
                "body_id": BODY_ID,
                "package_sha256": PACKAGE_SHA,
            }
        ],
    }


def test_no_active_person_revision_is_read_only_and_fail_closed(tmp_path: Path) -> None:
    value = twin.inspect_person_digital_twin_readiness(
        _profile(active=False),
        [],
        library_root=tmp_path,
    )

    assert value["state"] == "not-assembled"
    assert value["digital_twin_ready"] is False
    assert value["production_activation"] is False
    assert value["next_gate"] == "person_assembly"
    assert value["milestones"]["m1"]["state"] == "required"
    assert all(value["milestones"][key]["state"] == "blocked" for key in ("m2", "m3", "m4", "m5", "m6"))
    assert value["authority"] == {
        "browser_command_authority": False,
        "mutation_authority": False,
    }


def test_unique_m4_delegates_to_existing_operator_status_without_command_leak(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assembly = {"format": "bodyrig-person-assembly-receipt", "version": 2}
    monkeypatch.setattr(twin, "read_receipt", lambda *args, **kwargs: assembly)
    monkeypatch.setattr(
        twin,
        "inspect_candidate_release_status",
        lambda *args, **kwargs: {
            "state": "complete",
            "production_ready": True,
            "production_activation": True,
            "message": "Body physical release complete.",
        },
    )

    def releases(**kwargs):
        if kwargs["category"].startswith("hands-"):
            return ([{"release_id": "hfnrelease-" + "2" * 32}], [])
        return ([{"release_id": "wardrelease-" + "3" * 32}], [])

    monkeypatch.setattr(twin, "_valid_release_authorities", releases)
    composition_dir = tmp_path / "m4"
    composition_dir.mkdir()
    composition = {
        "authority_id": "dtcomp-" + "4" * 32,
        "body_id": BODY_ID,
        "bodyrig_revision": BODYRIG_REVISION,
        "hands_feet_nails": {"release_id": "hfnrelease-" + "5" * 32},
        "wardrobe": {"release_id": "wardrelease-" + "6" * 32},
    }
    monkeypatch.setattr(
        twin,
        "_valid_m4_authorities",
        lambda **kwargs: ([(composition_dir, composition)], []),
    )
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    monkeypatch.setattr(twin, "_acceptance_dir", lambda *args, **kwargs: (acceptance, None))
    monkeypatch.setattr(
        twin,
        "inspect_operator_status",
        lambda **kwargs: {
            "state": "complete",
            "m5_ready": True,
            "digital_twin_ready": True,
            "production_activation": True,
            "next_gate": "complete",
            "next_command": "SECRET-CANONICAL-COMMAND",
            "message": "Canonical M6 complete.",
            "expected_m6_release_id": "dtrelease-" + "7" * 32,
            "m5": {
                "m5_ready": True,
                "next_gate": "complete",
                "message": "M5 complete.",
                "next_command": "SECRET-M5-COMMAND",
                "platforms": {
                    "windows-unity-univrm": {
                        "ready": True,
                        "state": "complete",
                        "message": "Windows PASS",
                        "evidence_dir": "C:/evidence/windows",
                        "next_command": "SECRET-WINDOWS-COMMAND",
                    },
                    "android-quest-class": {
                        "ready": True,
                        "state": "complete",
                        "message": "Quest PASS",
                        "evidence_dir": "C:/evidence/quest",
                        "next_command": "SECRET-QUEST-COMMAND",
                    },
                },
            },
        },
    )

    value = twin.inspect_person_digital_twin_readiness(
        _profile(),
        [],
        library_root=tmp_path,
        operator_root=tmp_path,
    )

    assert value["state"] == "complete"
    assert value["digital_twin_ready"] is True
    assert value["production_activation"] is True
    assert all(value["milestones"][key]["complete"] is True for key in ("m1", "m2", "m3", "m4", "m5", "m6"))
    assert value["milestones"]["m2"]["authority_id"] == "hfnrelease-" + "5" * 32
    assert value["milestones"]["m3"]["authority_id"] == "wardrelease-" + "6" * 32
    assert value["m5"]["platforms"]["windows-unity-univrm"]["state"] == "complete"
    serialized = json.dumps(value, sort_keys=True)
    assert "SECRET" not in serialized
    assert "next_command" not in serialized
    assert value["authority"]["raw_next_command_exposed"] is False


def test_ambiguous_m4_stops_before_operator_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(twin, "read_receipt", lambda *args, **kwargs: {"version": 2})
    monkeypatch.setattr(
        twin,
        "inspect_candidate_release_status",
        lambda *args, **kwargs: {
            "state": "complete",
            "production_ready": True,
            "production_activation": True,
            "message": "Body complete.",
        },
    )
    monkeypatch.setattr(
        twin,
        "_valid_release_authorities",
        lambda **kwargs: ([{"release_id": "valid"}], []),
    )
    first = tmp_path / "m4-a"
    second = tmp_path / "m4-b"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(
        twin,
        "_valid_m4_authorities",
        lambda **kwargs: (
            [
                (first, {"authority_id": "dtcomp-" + "1" * 32}),
                (second, {"authority_id": "dtcomp-" + "2" * 32}),
            ],
            [],
        ),
    )

    def unexpected(**kwargs):
        raise AssertionError("ambiguous M4 must not delegate to operator status")

    monkeypatch.setattr(twin, "inspect_operator_status", unexpected)

    value = twin.inspect_person_digital_twin_readiness(
        _profile(),
        [],
        library_root=tmp_path,
    )

    assert value["milestones"]["m4"]["state"] == "blocked"
    assert "ambiguous" in value["milestones"]["m4"]["message"]
    assert value["milestones"]["m5"]["state"] == "blocked"
    assert value["digital_twin_ready"] is False
    assert value["production_activation"] is False


def test_acceptance_discovery_is_exact_and_ambiguous_fail_closed(tmp_path: Path) -> None:
    first = tmp_path / "acceptance-a"
    second = tmp_path / "acceptance-b"
    first.mkdir()
    second.mkdir()

    def job(path: Path) -> dict:
        return {
            "format": "bodyrig-ui-job",
            "kind": "body-build",
            "status": "succeeded",
            "person_id": PERSON_ID,
            "body_revision": BODY_REVISION,
            "canonical_body_id": BODY_ID,
            "bodyrig_revision": BODYRIG_REVISION,
            "acceptance_dir": str(path),
        }

    found, error = twin._acceptance_dir(
        [job(first)],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        bodyrig_revision=BODYRIG_REVISION,
    )
    assert found == first.resolve()
    assert error is None

    found, error = twin._acceptance_dir(
        [job(first), job(second)],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        bodyrig_revision=BODYRIG_REVISION,
    )
    assert found is None
    assert error is not None and "Multiple" in error


def test_drift_contract_is_get_only_and_has_no_digital_twin_action_surface() -> None:
    api = Path("bodyrig/digital_twin_control_plane_ui_api.py").read_text(encoding="utf-8")
    core = Path("bodyrig/digital_twin_control_plane_ui.py").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")

    assert '@router.get("/api/v1/people/{person_id}/digital-twin-readiness")' in api
    assert '@router.post("/api/v1/people/{person_id}/digital-twin-readiness' not in api
    assert "digital_twin_control_plane_ui_router" in app
    assert 'id="operator-digital-twin-badge"' in html
    assert 'id="operator-digital-twin-stages"' in html
    assert "renderDigitalTwin" in js
    assert "digitalTwinAttention" in js
    assert "/digital-twin-readiness" in js
    assert "next_command" not in js[js.index("function renderDigitalTwin"):js.index("function visible")]
    assert '"raw_next_command_exposed": False' in core
