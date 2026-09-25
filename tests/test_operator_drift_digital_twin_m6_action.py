from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import bodyrig.digital_twin_control_plane_ui as twin
from bodyrig.digital_twin_control_plane_ui_api import DigitalTwinControlActionRequest


PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
M4_ID = "dtcomp-" + "4" * 32
M6_ID = "dtrelease-" + "6" * 32


def _public_m6_status(tmp_path: Path) -> dict:
    return {
        "state": "required",
        "next_gate": "digital_twin_final_release",
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "body_revision": BODY_REVISION,
        "digital_twin_ready": False,
        "production_activation": False,
        "physical_acceptance_dir": str(tmp_path / "acceptance"),
        "milestones": {
            "m4": {
                "state": "complete",
                "complete": True,
                "authority_id": M4_ID,
            },
            "m5": {
                "state": "complete",
                "complete": True,
            },
            "m6": {
                "state": "required",
                "complete": False,
            },
        },
    }


def _raw_m6_status() -> dict:
    return {
        "state": "required",
        "next_gate": "digital_twin_final_release",
        "next_command": "CANONICAL-M6-COMMAND",
        "m5_ready": True,
        "digital_twin_release_eligible": True,
        "digital_twin_ready": False,
        "production_activation": False,
        "expected_m6_release_id": M6_ID,
        "m5": {
            "m5_ready": True,
            "next_gate": "complete",
        },
    }


def test_m6_action_catalog_is_command_free_and_explicitly_production_bound() -> None:
    actions = twin._typed_actions(
        state="required",
        next_gate="digital_twin_final_release",
        m5_detail={"m5_ready": True, "next_gate": "digital_twin_final_release"},
    )

    assert actions == [
        {
            "id": "finalize-m6",
            "label": "Finalisér M6 production release",
            "requires_confirmation": True,
            "production_activation": True,
        }
    ]
    assert all("command" not in item for item in actions)
    assert twin._typed_actions(
        state="required",
        next_gate="digital_twin_final_release",
        m5_detail={"m5_ready": False, "next_gate": "digital_twin_final_release"},
    ) == []
    assert twin._typed_actions(
        state="required",
        next_gate="digital_twin_final_release",
        m5_detail={"m5_ready": True, "next_gate": "m5:android-quest-class"},
    ) == []


def test_m6_request_forbids_command_smuggling_and_unknown_actions() -> None:
    value = DigitalTwinControlActionRequest(
        action="finalize-m6",
        confirm_production_activation=True,
    )
    assert value.confirm_production_activation is True

    with pytest.raises(ValidationError):
        DigitalTwinControlActionRequest.model_validate(
            {
                "action": "finalize-m6",
                "confirm_production_activation": True,
                "command": "Write-Host nope",
            }
        )
    with pytest.raises(ValidationError):
        DigitalTwinControlActionRequest(action="advance-m6")


def test_finalize_m6_requires_explicit_confirmation_before_status_or_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        twin,
        "inspect_person_digital_twin_readiness",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("missing confirmation must stop before status")
        ),
    )
    monkeypatch.setattr(
        twin,
        "launch_canonical_operator",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("missing confirmation must never launch")
        ),
    )

    with pytest.raises(
        twin.DigitalTwinControlPlaneError,
        match="eksplicit production-activation confirmation",
    ):
        twin.finalize_person_digital_twin_m6(
            {"person_id": PERSON_ID},
            [],
            library_root=tmp_path,
            operator_root=tmp_path,
            confirm_production_activation=False,
        )


def test_finalize_m6_recomputes_and_launches_only_exact_canonical_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    public = _public_m6_status(tmp_path)
    monkeypatch.setattr(
        twin,
        "inspect_person_digital_twin_readiness",
        lambda *args, **kwargs: public,
    )
    seen_raw: dict = {}

    def inspect_raw(**kwargs):
        seen_raw.update(kwargs)
        return _raw_m6_status()

    monkeypatch.setattr(twin, "inspect_operator_status", inspect_raw)
    launched: dict = {}

    def launch(command, *, category, context, cwd):
        launched.update(
            {
                "command": command,
                "category": category,
                "context": context,
                "cwd": cwd,
            }
        )
        return {"launch_id": "digital-twin-" + "a" * 32, "pid": 4242}

    monkeypatch.setattr(twin, "launch_canonical_operator", launch)

    result = twin.finalize_person_digital_twin_m6(
        {"person_id": PERSON_ID},
        [],
        library_root=tmp_path,
        operator_root=tmp_path,
        confirm_production_activation=True,
    )

    expected_composition = (
        tmp_path
        / "digital-twin-composition-authorities"
        / PERSON_ID
        / PERSON_REVISION
        / M4_ID
    ).resolve()
    assert seen_raw["composition_authority_dir"] == expected_composition
    assert seen_raw["acceptance_dir"] == (tmp_path / "acceptance").resolve()
    assert seen_raw["library_root"] == tmp_path.resolve()
    assert seen_raw["operator_root"] == tmp_path.resolve()
    assert launched["command"] == "CANONICAL-M6-COMMAND"
    assert launched["category"] == "digital-twin"
    assert launched["cwd"] == tmp_path.resolve()
    assert launched["context"] == {
        "action": "finalize-m6",
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "body_revision": BODY_REVISION,
        "gate": "digital_twin_final_release",
        "composition_authority_id": M4_ID,
        "expected_m6_release_id": M6_ID,
        "production_activation_requested": True,
    }
    assert result["launched"] is True
    assert result["action"] == "finalize-m6"
    assert result["expected_m6_release_id"] == M6_ID
    assert result["production_activation"] is False
    assert result["production_activation_requested"] is True
    assert result["strict_readback_required"] is True


@pytest.mark.parametrize(
    ("public_patch", "raw_patch"),
    [
        ({"state": "complete", "next_gate": "complete", "digital_twin_ready": True, "production_activation": True}, {}),
        ({"state": "required", "next_gate": "digital_twin_platform_acceptance"}, {}),
        ({}, {"next_gate": "digital_twin_platform_acceptance"}),
        ({}, {"m5_ready": False}),
        ({}, {"digital_twin_release_eligible": False}),
        ({}, {"digital_twin_ready": True, "production_activation": True}),
        ({}, {"expected_m6_release_id": ""}),
        ({}, {"expected_m6_release_id": "dtrelease-not-canonical"}),
        ({}, {"next_command": None}),
    ],
)
def test_finalize_m6_fails_closed_when_gate_or_authority_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    public_patch: dict,
    raw_patch: dict,
) -> None:
    public = {**_public_m6_status(tmp_path), **public_patch}
    monkeypatch.setattr(
        twin,
        "inspect_person_digital_twin_readiness",
        lambda *args, **kwargs: public,
    )
    monkeypatch.setattr(
        twin,
        "inspect_operator_status",
        lambda **kwargs: {**_raw_m6_status(), **raw_patch},
    )
    monkeypatch.setattr(
        twin,
        "launch_canonical_operator",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid M6 gate must never launch")
        ),
    )

    with pytest.raises(twin.DigitalTwinControlPlaneError):
        twin.finalize_person_digital_twin_m6(
            {"person_id": PERSON_ID},
            [],
            library_root=tmp_path,
            operator_root=tmp_path,
            confirm_production_activation=True,
        )


def test_m6_browser_path_requires_confirmation_and_never_receives_command() -> None:
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    api = Path("bodyrig/digital_twin_control_plane_ui_api.py").read_text(encoding="utf-8")
    core = Path("bodyrig/digital_twin_control_plane_ui.py").read_text(encoding="utf-8")

    m6_ui = js[js.index("async function runDigitalTwinM6"):js.index("function renderDigitalTwin(")]
    assert "window.confirm(" in m6_ui
    assert 'action: "finalize-m6"' in m6_ui
    assert "confirm_production_activation: true" in m6_ui
    assert "next_command" not in m6_ui
    assert "command" not in m6_ui

    assert 'Field(pattern=r"^(advance-m5|finalize-m6)$")' in api
    assert "confirm_production_activation: bool = False" in api
    assert "finalize_person_digital_twin_m6" in core
    assert "DIGITAL_TWIN_RELEASE_ID_RE.fullmatch(expected_release_id)" in core
    assert '"production_activation": False' in core
    assert '"strict_readback_required": True' in core
