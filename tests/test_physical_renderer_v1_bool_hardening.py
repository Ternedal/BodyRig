from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL_READERS = (
    "run-windows-renderer-probe.ps1",
    "run-quest-renderer-probe.ps1",
    "record-renderer-acceptance.ps1",
)


def test_low_level_physical_readers_use_bool_safe_numeric_v1_guard() -> None:
    for relative in PHYSICAL_READERS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "function Test-V1Version($Value)" in source, relative
        assert "$Value -is [bool]" in source, relative
        assert "$Value -isnot [ValueType]" in source, relative
        assert "[decimal]$Value -eq [decimal]1" in source, relative
        assert "[int]$acceptance.version" not in source, relative
        assert "[int]$report.version" not in source, relative
        assert "[int]$skinQa.version" not in source, relative
        assert "[int]$runtime.version" not in source, relative
        assert "[int]$probe.version" not in source, relative
        assert "[int]$deformation.version" not in source, relative


def test_probe_implementations_guard_all_persisted_v1_authority() -> None:
    for relative in ("run-windows-renderer-probe.ps1", "run-quest-renderer-probe.ps1"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "Test-V1Version $acceptance.version" in source, relative
        assert "Test-V1Version $probe.version" in source, relative
        assert "Test-V1Version $deformation.version" in source, relative


def test_renderer_acceptance_guards_all_persisted_v1_authority() -> None:
    source = (ROOT / "record-renderer-acceptance.ps1").read_text(encoding="utf-8")
    for value in ("$report.version", "$skinQa.version", "$runtime.version", "$probe.version", "$deformation.version"):
        assert f"Test-V1Version {value}" in source, value


def test_low_level_physical_reader_scope_is_explicit() -> None:
    discovered = tuple(
        sorted(
            path.name
            for path in ROOT.glob("*.ps1")
            if path.name in PHYSICAL_READERS
            and "bodyrig-renderer-probe" in path.read_text(encoding="utf-8")
            and "bodyrig-deformation-probe" in path.read_text(encoding="utf-8")
        )
    )
    assert discovered == tuple(sorted(PHYSICAL_READERS))
