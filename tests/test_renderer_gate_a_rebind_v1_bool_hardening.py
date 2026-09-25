from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REBINDS = (
    "rebind-gate-a-renderer-revision.ps1",
    "rebind-gate-a-renderer-assembly-revision.ps1",
    "rebind-gate-a-renderer-build-revision.ps1",
    "rebind-gate-a-renderer-package-revision.ps1",
    "rebind-gate-a-renderer-shader-revision.ps1",
)


def test_renderer_gate_a_rebinds_reject_bool_and_string_v1_authority() -> None:
    for relative in REBINDS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "$sourceVersion = $sourceAcceptance.version" in source, relative
        assert "$null -eq $sourceVersion" in source, relative
        assert "$sourceVersion -is [bool]" in source, relative
        assert "$sourceVersion -isnot [ValueType]" in source, relative
        assert "[decimal]$sourceVersion -ne [decimal]1" in source, relative
        assert "[int]$sourceAcceptance.version" not in source, relative


def test_renderer_gate_a_rebind_scope_is_complete() -> None:
    discovered = tuple(
        sorted(
            path.name
            for path in ROOT.glob("rebind-gate-a-renderer*.ps1")
            if "sourceAcceptance.version" in path.read_text(encoding="utf-8")
        )
    )
    assert discovered == tuple(sorted(REBINDS))
