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


def _public_m5_status(tmp_path: Path, *, platform: str = "windows-unity-univrm") -> dict:
    return {
        "state": "required",
        "next_gate": "digital_twin_platform_acceptance",
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "body_revision": BODY_REVISION,
        "physical_acceptance_dir": str(tmp_path / "acceptance"),
        "milestones": {
            "m4": {
                "state": "complete",
                "complete": True,
                "authority_id": M4_ID,
            }
        },
        "m5": {
            "m5_ready": False,
            "next_gate": f"m5:{platform}",
        },
    }


def _raw_m5_status(*, platform: str = "windows-unity-univrm") -> dict:
    return {
        "state": "required",
        "next_gate": "digital_twin_platform_acceptance",
        "next_command": "CANONICAL-M5-COMMAND",
        "m5": {
            "m5_ready": False,
            "next_gate": f"m5:{platform}",
        },
    }


def test_public_typed_action_catalog_never_contains_command() -> None:
    actions = twin._typed_actions(
        state="required",
        next_gate="digital_twin_platform_acceptance",
        m5_detail={
            "m5_ready": False,
            "next_gate": "m5:windows-unity-univrm",
        },
    )

    assert actions == [
        {
            "id": "advance-m5",
            "platform": "windows-unity-univrm",
            "label": "Kør næste M5 Windows-trin",
        }
    ]
    assert all("command" not in item for item in actions)
    assert twin._typed_actions(
        state="required",
        next_gate="digital_twin_final_release",
        m5_detail={"next_gate": "complete"},
    ) == []
    assert twin._typed_actions(
        state="required",
        next_gate="digital_twin_platform_acceptance",
        m5_detail={"next_gate": "m5:not-supported"},
    ) == []


def test_m5_action_request_forbids_browser_command_smuggling() -> None:
    assert DigitalTwinControlActionRequest(action="advance-m5").action == "advance-m5"
    with pytest.raises(ValidationError):
        DigitalTwinControlActionRequest.model_validate(
            {"action": "advance-m5", "command": "Write-Host nope"}
        )
    with pytest.raises(ValidationError):
        DigitalTwinControlActionRequest(action="advance-m6")


def test_advance_m5_recomputes_and_launches_only_exact_canonical_m5_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    public = _public_m5_status(tmp_path)
    monkeypatch.setattr(
        twin,
        "inspect_person_digital_twin_readiness",
        lambda *args, **kwargs: public,
    )
    seen_raw: dict = {}

    def inspect_raw(**kwargs):
        seen_raw.update(kwargs)
        return _raw_m5_status()

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

    result = twin.advance_person_digital_twin_m5(
        {"person_id": PERSON_ID},
        [],
        library_root=tmp_path,
        operator_root=tmp_path,
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
    assert launched["command"] == "CANONICAL-M5-COMMAND"
    assert launched["category"] == "digital-twin"
    assert launched["cwd"] == tmp_path.resolve()
    assert launched["context"] == {
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "body_revision": BODY_REVISION,
        "gate": "digital_twin_platform_acceptance",
        "platform": "windows-unity-univrm",
        "composition_authority_id": M4_ID,
    }
    assert result["launched"] is True
    assert result["action"] == "advance-m5"
    assert result["platform"] == "windows-unity-univrm"
    assert result["production_activation"] is False


@pytest.mark.parametrize(
    ("state", "gate"),
    [
        ("required", "digital_twin_final_release"),
        ("required", "body_physical:runtime-visual-authority"),
        ("blocked", "digital_twin_platform_acceptance"),
        ("complete", "complete"),
    ],
)
def test_advance_m5_refuses_non_machine_m5_public_gates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    state: str,
    gate: str,
) -> None:
    public = _public_m5_status(tmp_path)
    public["state"] = state
    public["next_gate"] = gate
    monkeypatch.setattr(
        twin,
        "inspect_person_digital_twin_readiness",
        lambda *args, **kwargs: public,
    )
    monkeypatch.setattr(
        twin,
        "inspect_operator_status",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("non-M5 public gate must stop before raw command inspection")
        ),
    )
    monkeypatch.setattr(
        twin,
        "launch_canonical_operator",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("non-M5 public gate must never launch")
        ),
    )

    with pytest.raises(
        twin.DigitalTwinControlPlaneError,
        match="ikke et maskinelt M5 realization-trin",
    ):
        twin.advance_person_digital_twin_m5(
            {"person_id": PERSON_ID},
            [],
            library_root=tmp_path,
            operator_root=tmp_path,
        )


def test_advance_m5_refuses_gate_change_between_status_and_click(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        twin,
        "inspect_person_digital_twin_readiness",
        lambda *args, **kwargs: _public_m5_status(tmp_path),
    )
    monkeypatch.setattr(
        twin,
        "inspect_operator_status",
        lambda **kwargs: {
            "state": "required",
            "next_gate": "digital_twin_final_release",
            "next_command": "DANGEROUS-M6-COMMAND",
            "m5": {"next_gate": "complete"},
        },
    )
    monkeypatch.setattr(
        twin,
        "launch_canonical_operator",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("changed gate must never launch")
        ),
    )

    with pytest.raises(
        twin.DigitalTwinControlPlaneError,
        match="ændrede sig",
    ):
        twin.advance_person_digital_twin_m5(
            {"person_id": PERSON_ID},
            [],
            library_root=tmp_path,
            operator_root=tmp_path,
        )


def test_advance_m5_refuses_unsupported_platform_after_recompute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        twin,
        "inspect_person_digital_twin_readiness",
        lambda *args, **kwargs: _public_m5_status(tmp_path),
    )
    monkeypatch.setattr(
        twin,
        "inspect_operator_status",
        lambda **kwargs: _raw_m5_status(platform="not-supported"),
    )
    monkeypatch.setattr(
        twin,
        "launch_canonical_operator",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unsupported M5 platform must never launch")
        ),
    )

    with pytest.raises(
        twin.DigitalTwinControlPlaneError,
        match="ikke sikkert launch-klar",
    ):
        twin.advance_person_digital_twin_m5(
            {"person_id": PERSON_ID},
            [],
            library_root=tmp_path,
            operator_root=tmp_path,
        )


def test_m5_launch_is_auditable_in_operator_history() -> None:
    core = Path("bodyrig/digital_twin_control_plane_ui.py").read_text(encoding="utf-8")
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    assert 'category="digital-twin"' in core
    assert '"platform": platform' in core
    assert '"composition_authority_id": authority_id' in core
    assert '<option value="digital-twin">Digital twin</option>' in html
    assert '["Platform", context.platform]' in js
    assert '["M4 composition authority", context.composition_authority_id]' in js
    assert "context.person_revision" in js
