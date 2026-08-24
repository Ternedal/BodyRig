from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.acceptance_status_cli import _operator_command, _status_exit_code
from bodyrig.reference_acceptance_policy import _load_contract, apply_reference_policy


REPO = Path(__file__).resolve().parents[1]


def _status(gate: str) -> AcceptanceStatus:
    return AcceptanceStatus(
        state="human-review",
        gate=gate,
        acceptance_dir=r"C:\acceptance",
        body_id="person-a",
        bodyrig_revision="a" * 40,
        message="review required",
        next_command="unsafe legacy command",
    )


def _write_reference_pair(directory: Path, *, renderer_version: str | None = None, unity_version: str | None = None, sequence: str | None = None) -> None:
    contract = _load_contract()
    assert contract is not None
    evidence = directory / "windows-evidence"
    evidence.mkdir(parents=True)
    (evidence / "windows-probe.json").write_text(
        json.dumps(
            {
                "active_renderer": {
                    "name": contract["renderer_name"],
                    "version": renderer_version or contract["renderer_version"],
                },
                "unity_version": unity_version or contract["unity_editor_version"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (evidence / "windows-deformation-probe.json").write_text(
        json.dumps(
            {
                "unity_version": unity_version or contract["unity_editor_version"],
                "sequence_revision": sequence or contract["deformation_sequence_revision"],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_windows_probe_status_command_uses_contract_bound_wrapper() -> None:
    status = _operator_command(_status("windows-probe"))
    assert status.next_command is not None
    assert ".\\run-reference-windows-renderer-probe.ps1" in status.next_command
    assert "-AcceptanceDir" in status.next_command
    assert ".\\run-windows-renderer-probe.ps1" not in status.next_command


def test_windows_status_command_uses_reference_attestation_helper() -> None:
    status = _operator_command(_status("windows-attestation"))
    assert status.next_command is not None
    assert ".\\record-reference-renderer-acceptance.ps1" in status.next_command
    assert '-Platform "windows-unity-univrm"' in status.next_command
    assert "-QualityNote" in status.next_command
    assert "RendererName" not in status.next_command
    assert "RendererVersion" not in status.next_command


def test_quest_probe_status_command_uses_contract_bound_wrapper() -> None:
    status = _operator_command(_status("quest-probe"))
    assert status.next_command is not None
    assert ".\\run-reference-quest-renderer-probe.ps1" in status.next_command
    assert "-AcceptanceDir" in status.next_command
    assert ".\\run-quest-renderer-probe.ps1" not in status.next_command


def test_quest_status_command_uses_reference_attestation_helper() -> None:
    status = _operator_command(_status("quest-attestation"))
    assert status.next_command is not None
    assert ".\\record-reference-renderer-acceptance.ps1" in status.next_command
    assert '-Platform "android-quest-class"' in status.next_command
    assert "-QualityNote" in status.next_command
    assert "RendererName" not in status.next_command
    assert "RendererVersion" not in status.next_command


def test_release_status_command_uses_contract_bound_final_wrapper() -> None:
    ready = replace(_status("release"), state="ready")
    status = _operator_command(ready)
    assert status.next_command is not None
    assert ".\\complete-reference-acceptance.ps1" in status.next_command
    assert "-AcceptanceDir" in status.next_command
    assert ".\\complete-acceptance.ps1" not in status.next_command


def test_completed_release_status_is_not_rewritten() -> None:
    complete = replace(_status("release"), state="complete", next_command=None)
    assert _operator_command(complete) == complete


def test_unrelated_status_command_is_unchanged() -> None:
    original = _status("gate-a")
    assert _operator_command(original) == original


def test_blocked_reference_status_is_nonzero_but_normal_states_are_success() -> None:
    assert _status_exit_code(replace(_status("reference-contract"), state="blocked", next_command=None)) == 3
    assert _status_exit_code(replace(_status("windows-probe"), state="ready")) == 0
    assert _status_exit_code(_status("windows-attestation")) == 0
    assert _status_exit_code(replace(_status("release"), state="complete", next_command=None)) == 0


def test_reference_policy_leaves_empty_transactional_layout_unchanged(tmp_path: Path) -> None:
    status = replace(_status("windows-probe"), acceptance_dir=str(tmp_path), state="ready")
    assert apply_reference_policy(status) == status


def test_reference_policy_accepts_contract_matching_transactional_evidence(tmp_path: Path) -> None:
    _write_reference_pair(tmp_path)
    status = replace(_status("windows-attestation"), acceptance_dir=str(tmp_path))
    assert apply_reference_policy(status) == status


def test_reference_policy_blocks_wrong_renderer_version_before_human_review(tmp_path: Path) -> None:
    _write_reference_pair(tmp_path, renderer_version="wrong-renderer")
    status = replace(_status("windows-attestation"), acceptance_dir=str(tmp_path))

    blocked = apply_reference_policy(status)
    assert blocked.state == "blocked"
    assert blocked.gate == "reference-contract"
    assert blocked.next_command is None
    assert "renderer version" in blocked.message


def test_reference_policy_blocks_wrong_unity_before_human_review(tmp_path: Path) -> None:
    _write_reference_pair(tmp_path, unity_version="6000.3.99f1")
    status = replace(_status("windows-attestation"), acceptance_dir=str(tmp_path))

    blocked = apply_reference_policy(status)
    assert blocked.state == "blocked"
    assert blocked.gate == "reference-contract"
    assert "Unity version" in blocked.message


def test_reference_policy_blocks_wrong_deformation_sequence_before_human_review(tmp_path: Path) -> None:
    _write_reference_pair(tmp_path, sequence="different-sequence")
    status = replace(_status("windows-attestation"), acceptance_dir=str(tmp_path))

    blocked = apply_reference_policy(status)
    assert blocked.state == "blocked"
    assert blocked.gate == "reference-contract"
    assert "deformation sequence" in blocked.message


def test_reference_policy_blocks_unfinished_legacy_root_evidence(tmp_path: Path) -> None:
    (tmp_path / "windows-probe.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "windows-deformation-probe.json").write_text("{}\n", encoding="utf-8")
    status = replace(_status("quest-probe"), acceptance_dir=str(tmp_path), state="ready")

    blocked = apply_reference_policy(status)
    assert blocked.state == "blocked"
    assert blocked.gate == "reference-layout"
    assert blocked.next_command is None
    assert "Legacy root renderer evidence" in blocked.message
    assert "fresh Gate A acceptance bundle" in blocked.message
    assert "windows-probe.json" in blocked.message


def test_reference_policy_keeps_already_completed_historical_release_readable(tmp_path: Path) -> None:
    (tmp_path / "windows-probe.json").write_text("{}\n", encoding="utf-8")
    complete = replace(_status("release"), acceptance_dir=str(tmp_path), state="complete", next_command=None)
    assert apply_reference_policy(complete) == complete


def test_packaged_and_powershell_status_entrypoints_use_operator_cli() -> None:
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    powershell = (REPO / "physical-acceptance-status.ps1").read_text(encoding="utf-8")
    assert 'bodyrig-acceptance-status = "bodyrig.acceptance_status_cli:main"' in pyproject
    assert '"bodyrig.acceptance_status_cli"' in powershell


def test_operator_docs_do_not_ask_human_to_type_renderer_version() -> None:
    for path in (REPO / "README.md", REPO / "docs" / "RIG_ACCEPTANCE.md"):
        text = path.read_text(encoding="utf-8")
        assert text.count(".\\record-reference-renderer-acceptance.ps1") >= 2
        assert '-RendererVersion "Unity ' not in text
