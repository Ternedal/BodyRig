from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.acceptance_status import (
    AcceptanceStatusError,
    GateAInfo,
    PlatformPaths,
    _renderer_attestation_command,
)


def _paths(tmp_path: Path, *, renderer: dict | None) -> tuple[GateAInfo, PlatformPaths]:
    acceptance = tmp_path / "acceptance"
    evidence = acceptance / "windows-evidence"
    evidence.mkdir(parents=True)
    probe = evidence / "windows-probe.json"
    probe.write_text(json.dumps({"active_renderer": renderer}) + "\n", encoding="utf-8")
    deformation = evidence / "windows-deformation-probe.json"
    deformation.write_text("{}\n", encoding="utf-8")
    gate = GateAInfo(
        acceptance / "bodyrig-acceptance.json",
        "bodyid-" + "1" * 24,
        "a" * 40,
        "b" * 64,
        "c" * 64,
    )
    return gate, PlatformPaths(probe, deformation, acceptance / "bodyrig-renderer-acceptance-windows.json", "dedicated")


def test_canonical_attestation_command_is_directly_runnable_and_probe_bound(tmp_path: Path) -> None:
    gate, paths = _paths(
        tmp_path,
        renderer={
            "name": "BodyRig Reference Renderer",
            "version": "reference-v1/univrm-0.131.2",
        },
    )

    command = _renderer_attestation_command(
        gate=gate,
        acceptance_dir=tmp_path / "acceptance",
        paths=paths,
        platform="windows-unity-univrm",
        quality_note="<your physical review>",
    )

    assert "record-renderer-acceptance.ps1" in command
    assert "-Pass -ConfirmQualityChecklist" in command
    assert '-RendererName "BodyRig Reference Renderer"' in command
    assert '-RendererVersion "reference-v1/univrm-0.131.2"' in command
    assert "<exact version>" not in command
    assert str(paths.probe) in command
    assert str(paths.deformation) in command


def test_canonical_attestation_command_fails_closed_without_probe_renderer_identity(tmp_path: Path) -> None:
    gate, paths = _paths(tmp_path, renderer={"name": "BodyRig Reference Renderer", "version": ""})

    with pytest.raises(AcceptanceStatusError, match="exact renderer name/version"):
        _renderer_attestation_command(
            gate=gate,
            acceptance_dir=tmp_path / "acceptance",
            paths=paths,
            platform="windows-unity-univrm",
            quality_note="<your physical review>",
        )


def test_record_renderer_contract_still_requires_explicit_quality_confirmation() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "record-renderer-acceptance.ps1").read_text(encoding="utf-8")
    assert "[Parameter(Mandatory = $true)][switch]$ConfirmQualityChecklist" in script
    assert "if (-not $ConfirmQualityChecklist)" in script