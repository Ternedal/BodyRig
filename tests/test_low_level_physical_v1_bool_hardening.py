from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATIONS = (
    "run-windows-renderer-probe.ps1",
    "run-quest-renderer-probe.ps1",
    "record-renderer-acceptance.ps1",
)

COMMON_AUTHORITIES = (
    "acceptance.version",
    "probe.version",
    "deformation.version",
)

RENDERER_ATTESTATION_AUTHORITIES = (
    "report.version",
    "skinQa.version",
    "runtime.version",
    "probe.version",
    "deformation.version",
)


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_low_level_physical_implementations_use_bool_safe_numeric_v1_guard() -> None:
    for relative in IMPLEMENTATIONS:
        source = _source(relative)
        assert "function Test-V1Version($Value)" in source, relative
        assert "$null -eq $Value" in source, relative
        assert "$Value -is [bool]" in source, relative
        assert "$Value -isnot [ValueType]" in source, relative
        assert "[decimal]$Value -eq [decimal]1" in source, relative


def test_windows_and_quest_probe_authority_call_sites_use_v1_guard() -> None:
    for relative in ("run-windows-renderer-probe.ps1", "run-quest-renderer-probe.ps1"):
        source = _source(relative)
        for authority in COMMON_AUTHORITIES:
            assert f"Test-V1Version ${authority}" in source, (relative, authority)
            assert f"[int]${authority}" not in source, (relative, authority)


def test_renderer_attestation_writer_authority_call_sites_use_v1_guard() -> None:
    source = _source("record-renderer-acceptance.ps1")
    for authority in RENDERER_ATTESTATION_AUTHORITIES:
        assert f"Test-V1Version ${authority}" in source, authority
        assert f"[int]${authority}" not in source, authority


def test_low_level_physical_scope_is_explicit_and_complete() -> None:
    assert tuple(sorted(path.name for path in (ROOT / name for name in IMPLEMENTATIONS))) == tuple(
        sorted(IMPLEMENTATIONS)
    )
    for relative in IMPLEMENTATIONS:
        assert (ROOT / relative).is_file(), relative
