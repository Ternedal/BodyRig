from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = (
    "run-reference-windows-renderer-probe.ps1",
    "run-reference-quest-renderer-probe.ps1",
    "record-reference-renderer-acceptance.ps1",
    "complete-reference-acceptance.ps1",
)


def test_reference_physical_wrappers_use_bool_safe_numeric_v1_guard() -> None:
    for relative in WRAPPERS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "function Test-V1Version($Value)" in source, relative
        assert "$Value -is [bool]" in source, relative
        assert "$Value -isnot [ValueType]" in source, relative
        assert "[decimal]$Value -eq [decimal]1" in source, relative
        assert "[int]$probe.version" not in source, relative
        assert "[int]$deformation.version" not in source, relative


def test_reference_wrapper_evidence_call_sites_use_v1_guard() -> None:
    for relative in WRAPPERS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "Test-V1Version $probe.version" in source, relative
        assert "Test-V1Version $deformation.version" in source, relative

    final_release = (ROOT / "complete-reference-acceptance.ps1").read_text(encoding="utf-8")
    assert "Test-V1Version $attestation.version" in final_release
    assert "[int]$attestation.version" not in final_release


def test_reference_wrapper_scope_is_explicit() -> None:
    discovered = tuple(
        sorted(
            path.name
            for path in ROOT.glob("*reference*.ps1")
            if "bodyrig-renderer-probe" in path.read_text(encoding="utf-8")
            and "bodyrig-deformation-probe" in path.read_text(encoding="utf-8")
            and path.name in WRAPPERS
        )
    )
    assert discovered == tuple(sorted(WRAPPERS))
