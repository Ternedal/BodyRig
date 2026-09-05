from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import bodyrig.high_fidelity_release_readiness_cli as cli


REVISION = "c" * 40
OTHER_REVISION = "d" * 40


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    for relative in cli.CANONICAL_OPERATOR_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.suffix == ".json" else "exit 0\n", encoding="utf-8")
    return root


def _status(*, accepted_revision: str | None = None, acceptance: Path | None = None) -> dict:
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
        "physical_acceptance_dir": str(acceptance) if acceptance is not None else None,
        "next_gate": {
            "gate": "physical_windows_acceptance",
            "command": '.\\run-windows-renderer-probe.ps1 -AcceptanceDir "C:\\hf"',
            "operator_input_required": True,
            "reason": "run exact Windows probe",
        },
        "production_ready": False,
        "production_activation": False,
    }


def test_clean_matching_checkout_routes_windows_through_reference_wrapper(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    acceptance = tmp_path / "physical"
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))

    result = cli.bind_operator_checkout(_status(accepted_revision=REVISION, acceptance=acceptance), root)

    assert result["state"] == "physical-windows-acceptance-required"
    assert result["operator_checkout"]["authorized"] is True
    assert result["operator_checkout"]["revision"] == REVISION
    assert result["operator_checkout"]["accepted_revision"] == REVISION
    command = result["next_gate"]["command"]
    assert command.startswith('& "')
    assert str((root / "run-reference-windows-renderer-probe.ps1").resolve()) in command
    assert "run-windows-renderer-probe.ps1" not in command
    assert f"-AcceptanceDir '{acceptance.resolve()}'" in command


def test_attestation_command_routes_through_reference_policy_wrapper(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    acceptance = tmp_path / "physical"
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    status = _status(accepted_revision=REVISION, acceptance=acceptance)
    status["next_gate"]["command"] = (
        '.\\record-renderer-acceptance.ps1 -AcceptanceReport "C:\\hf\\bodyrig-acceptance.json" '
        '-Platform "windows-unity-univrm" -Pass -RendererName "BodyRig Reference Renderer" '
        '-RendererVersion "<exact version>" -QualityNote "<your physical review>"'
    )

    result = cli.bind_operator_checkout(status, root)
    command = result["next_gate"]["command"]

    assert str((root / "record-reference-renderer-acceptance.ps1").resolve()) in command
    assert "record-renderer-acceptance.ps1" not in command
    assert '-Platform "windows-unity-univrm"' in command
    assert "-ConfirmQualityChecklist" in command
    assert '-QualityNote "<your physical review>"' in command
    assert "-RendererName" not in command
    assert "-RendererVersion" not in command


def test_quest_probe_routes_through_reference_wrapper_with_pinned_adb_and_serial(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    acceptance = tmp_path / "physical"
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    monkeypatch.setattr(cli, "_quest_adb", lambda _root: Path(r"C:\PinnedUnity\adb.exe"))
    status = _status(accepted_revision=REVISION, acceptance=acceptance)
    status["state"] = "physical-quest-acceptance-required"
    status["next_gate"] = {
        "gate": "physical_quest_acceptance",
        "command": '.\\run-quest-renderer-probe.ps1 -AcceptanceDir "C:\\hf"',
        "operator_input_required": True,
        "reason": "run exact Quest probe",
    }

    result = cli.bind_operator_checkout(status, root, quest_serial="1WMHH123456789")
    command = result["next_gate"]["command"]

    assert str((root / "run-reference-quest-renderer-probe.ps1").resolve()) in command
    assert "run-quest-renderer-probe.ps1" not in command
    assert "-AdbExe 'C:\\PinnedUnity\\adb.exe'" in command
    assert "-Serial '1WMHH123456789'" in command


def test_release_routes_through_reference_release_wrapper(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    acceptance = tmp_path / "physical"
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    status = _status(accepted_revision=REVISION, acceptance=acceptance)
    status["state"] = "final-release-required"
    status["next_gate"] = {
        "gate": "final_release",
        "command": '.\\complete-acceptance.ps1 -AcceptanceReport "C:\\hf\\bodyrig-acceptance.json"',
        "operator_input_required": True,
        "reason": "complete release",
    }

    result = cli.bind_operator_checkout(status, root)
    command = result["next_gate"]["command"]

    assert str((root / "complete-reference-acceptance.ps1").resolve()) in command
    assert "complete-acceptance.ps1" not in command
    assert f"-AcceptanceDir '{acceptance.resolve()}'" in command


def test_reference_policy_block_removes_next_command(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    acceptance = tmp_path / "physical"
    acceptance.mkdir()
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    monkeypatch.setattr(cli, "inspect_acceptance_dir", lambda _path: SimpleNamespace())
    monkeypatch.setattr(
        cli,
        "apply_reference_policy",
        lambda _status: SimpleNamespace(
            state="blocked",
            gate="reference-contract",
            message="renderer evidence drifted from contract",
        ),
    )

    result = cli.bind_operator_checkout(_status(accepted_revision=REVISION, acceptance=acceptance), root)

    assert result["state"] == "blocked"
    assert result["next_gate"] is None
    assert result["production_ready"] is False
    assert result["production_activation"] is False
    assert result["reference_policy"]["authorized"] is False
    assert "reference-contract" in result["reference_policy"]["reason"]


def test_invalid_quest_serial_fails_closed(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    acceptance = tmp_path / "physical"
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))
    monkeypatch.setattr(cli, "_quest_adb", lambda _root: Path(r"C:\PinnedUnity\adb.exe"))
    status = _status(accepted_revision=REVISION, acceptance=acceptance)
    status["next_gate"]["command"] = '.\\run-quest-renderer-probe.ps1 -AcceptanceDir "C:\\hf"'

    try:
        cli.bind_operator_checkout(status, root, quest_serial="bad serial")
    except cli.HighFidelityReleaseReadinessCliError as exc:
        assert "serial" in str(exc).lower()
    else:
        raise AssertionError("invalid Quest serial must fail closed")


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


def test_missing_reference_operator_script_fails_closed(monkeypatch, tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "run-reference-windows-renderer-probe.ps1").unlink()
    monkeypatch.setattr(cli, "_git_state", lambda _root: (REVISION, True))

    try:
        cli.bind_operator_checkout(_status(accepted_revision=REVISION), root)
    except cli.HighFidelityReleaseReadinessCliError as exc:
        assert "missing" in str(exc).lower()
        assert "run-reference-windows-renderer-probe.ps1" in str(exc)
    else:
        raise AssertionError("missing canonical reference wrapper must fail closed")


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
