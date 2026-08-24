from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.acceptance_status_cli import _operator_command


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


def test_non_attestation_status_command_is_unchanged() -> None:
    original = _status("windows-probe")
    assert _operator_command(original) == original


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
