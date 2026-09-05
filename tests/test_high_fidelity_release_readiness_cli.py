from __future__ import annotations

import json
from pathlib import Path

import bodyrig.high_fidelity_release_readiness_cli as cli


REVISION = "c" * 40
OTHER_REVISION = "d" * 40


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "run-windows-renderer-probe.ps1").write_text("exit 0\n", encoding="utf-8")
    (root / "record-renderer-acceptance.ps1").write_text("exit 0\n", encoding="utf-8")
    return root


def _status(*, accepted_revision: str | None = None) -> dict:
    gates = []
    if accepted_revision is not None:
        gates.append(
            {
                "id": "physical_gate_a",
                "state": "pass",
                "evidence": {"bodyrig_revision": accepted_revision},
            }
        )
    return {
        "state": "physical-windows-acceptance-required",
        "gates": gates,
        "next_gate": {
            "gate": "physical_windows_acceptance",
            "command": '.\\run-windows-renderer-probe.ps1 -AcceptanceDir "C:\\hf"',
            "operator_input_required": True,
            "reason": "run exact Windows probe",
        },
        "production_ready": False,
        "production_activation": False,
    }


def test_clean_matching_checkout_authorizes_and_absolutizes_next_command(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))

    result = cli.bind_operator_checkout(_status(accepted_revision=REVISION), root)

    assert result["state"] == "physical-windows-acceptance-required"
    assert result["operator_checkout"]["authorized"] is True
    assert result["operator_checkout"]["revision"] == REVISION
    assert result["operator_checkout"]["accepted_revision"] == REVISION
    command = result["next_gate"]["command"]
    assert command.startswith('& "')
    assert str((root / "run-windows-renderer-probe.ps1").resolve()) in command
    assert '-AcceptanceDir "C:\\hf"' in command


def test_attestation_command_gets_required_checklist_and_exact_renderer_identity(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    acceptance = tmp_path / "physical"
    probe = acceptance / "windows-evidence" / "windows-probe.json"
    probe.parent.mkdir(parents=True)
    probe.write_text(
        json.dumps({"active_renderer": {"name": "BodyRig Reference Renderer", "version": "1.2.3+build.9"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    status = _status(accepted_revision=REVISION)
    status["physical_acceptance_dir"] = str(acceptance)
    status["next_gate"]["command"] = (
        '.\\record-renderer-acceptance.ps1 -AcceptanceReport "C:\\hf\\bodyrig-acceptance.json" '
        '-Platform "windows-unity-univrm" -Pass -RendererName "BodyRig Reference Renderer" '
        '-RendererVersion "<exact version>" -QualityNote "<your physical review>"'
    )

    result = cli.bind_operator_checkout(status, root)
    command = result["next_gate"]["command"]

    assert "-Pass -ConfirmQualityChecklist" in command
    assert "-RendererName 'BodyRig Reference Renderer'" in command
    assert "-RendererVersion '1.2.3+build.9'" in command
    assert "<exact version>" not in command
    assert str((root / "record-renderer-acceptance.ps1").resolve()) in command


def test_gate_a_revision_mismatch_blocks_and_removes_next_command(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(cli, "_git_state", lambda _root: (OTHER_REVISION, True))

    result = cli.bind_operator_checkout(_status(accepted_revision=REVISION), root)

    assert result["state"] == "blocked"
    assert result["next_gate"] is None
    assert result["production_ready"] is False
    assert result["production_activation"] is False
    assert result["operator_checkout"]["authorized"] is False
    assert REVISION in result["operator_checkout"]["reason"]


def test_dirty_checkout_blocks_even_before_gate_a(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, False))

    result = cli.bind_operator_checkout(_status(), root)

    assert result["state"] == "blocked"
    assert result["next_gate"] is None
    assert result["operator_checkout"]["clean"] is False
    assert result["operator_checkout"]["authorized"] is False


def test_missing_operator_script_fails_closed(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "run-windows-renderer-probe.ps1").unlink()
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))

    try:
        cli.bind_operator_checkout(_status(accepted_revision=REVISION), root)
    except cli.HighFidelityReleaseReadinessCliError as exc:
        assert "missing" in str(exc).lower()
    else:
        raise AssertionError("missing next operator script must fail closed")


def test_no_next_gate_can_report_complete_without_inventing_command(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    status = {
        "state": "production-ready",
        "gates": [{"id": "physical_gate_a", "state": "pass", "evidence": {"bodyrig_revision": REVISION}}],
        "next_gate": None,
        "production_ready": True,
        "production_activation": True,
    }

    result = cli.bind_operator_checkout(status, root)

    assert result["next_gate"] is None
    assert result["production_ready"] is True
    assert result["production_activation"] is True
    assert result["operator_checkout"]["authorized"] is True
