from pathlib import Path

import bodyrig.high_fidelity_hfn_migrated_readiness_cli as cli


PREVIEW = "hfpreview-" + "1" * 32
REV = "a" * 40
OTHER = "b" * 40


def _result(command: str | None = None) -> dict:
    return {
        "state": "physical-gate-a-required" if command else "incomplete",
        "next_gate": None if command is None else {
            "gate": "physical_gate_a",
            "command": command,
            "operator_input_required": True,
            "reason": "fresh Gate A required",
        },
        "hfn_migration_active": True,
        "legacy_bodyrig_revision": OTHER,
        "hfn_bodyrig_revision": REV,
        "production_ready": False,
        "production_activation": False,
    }


def test_migrated_checkout_must_equal_frozen_hfn_revision(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli.canonical_cli,
        "bind_operator_checkout",
        lambda result, _root, quest_serial=None: {
            **result,
            "operator_checkout": {
                "revision": OTHER,
                "clean": True,
                "authorized": True,
            },
        },
    )

    result = cli._bind(_result(), tmp_path, quest_serial=None)

    assert result["state"] == "blocked"
    assert result["next_gate"] is None
    assert result["operator_checkout"]["authorized"] is False
    assert REV in result["operator_checkout"]["reason"]


def test_migrated_gate_a_uses_migration_aware_handoff(monkeypatch, tmp_path: Path) -> None:
    command = "& 'C:\\BodyRig\\prepare-high-fidelity-physical-acceptance.ps1' -PreviewJobId 'hfpreview-x'"
    monkeypatch.setattr(
        cli.canonical_cli,
        "bind_operator_checkout",
        lambda result, _root, quest_serial=None: {
            **result,
            "operator_checkout": {
                "revision": REV,
                "clean": True,
                "authorized": True,
            },
        },
    )

    result = cli._bind(_result(command), tmp_path, quest_serial=None)

    assert result["operator_checkout"]["authorized"] is True
    assert "prepare-high-fidelity-migrated-physical-acceptance.ps1" in result["next_gate"]["command"]
    assert "prepare-high-fidelity-physical-acceptance.ps1" not in result["next_gate"]["command"]
