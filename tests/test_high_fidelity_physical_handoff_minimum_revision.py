from pathlib import Path

import bodyrig.high_fidelity_release_readiness_cli as cli


ROOT = Path(__file__).resolve().parents[1]


def test_status_and_prepare_wrapper_share_minimum_safe_handoff_revision() -> None:
    source = (ROOT / "prepare-high-fidelity-physical-acceptance.ps1").read_text(encoding="utf-8")

    assert cli.MINIMUM_PHYSICAL_HANDOFF_REVISION in source
    assert "git -C $RepoRoot cat-file -e $anchorSpec" in source
    assert "git -C $RepoRoot merge-base --is-ancestor $MinimumRevision $CurrentHead" in source
    assert "Update the integration checkout before creating fresh Gate A" in source


def test_prepare_wrapper_proves_minimum_ancestry_before_python_can_create_gate_a() -> None:
    source = (ROOT / "prepare-high-fidelity-physical-acceptance.ps1").read_text(encoding="utf-8")

    ancestry = source.index("Assert-MinimumPhysicalHandoffRevision -RepoRoot $repoRoot")
    python_lookup = source.index("Get-Command python")
    physical_cli = source.index("-m bodyrig.high_fidelity_physical_acceptance")

    assert ancestry < python_lookup < physical_cli


def test_prepare_wrapper_matches_status_python_selection_and_checkout_import_authority() -> None:
    prepare = (ROOT / "prepare-high-fidelity-physical-acceptance.ps1").read_text(encoding="utf-8")
    status = (ROOT / "high-fidelity-physical-status.ps1").read_text(encoding="utf-8")

    for token in (
        '.venv\\Scripts\\python.exe',
        "Test-Path -LiteralPath $pythonCandidate -PathType Leaf",
        "Get-Command python -ErrorAction SilentlyContinue",
        '$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }',
        "bodyrig.__file__",
    ):
        assert token in prepare
        assert token in status

    venv = prepare.index('.venv\\Scripts\\python.exe')
    path_fallback = prepare.index("Get-Command python -ErrorAction SilentlyContinue")
    pythonpath = prepare.index("$env:PYTHONPATH = if")
    module_authority = prepare.index("bodyrig.__file__")
    physical_cli = prepare.index("-m bodyrig.high_fidelity_physical_acceptance")

    assert venv < path_fallback < pythonpath < module_authority < physical_cli


def test_minimum_revision_is_canonical_git_sha() -> None:
    value = cli.MINIMUM_PHYSICAL_HANDOFF_REVISION
    assert len(value) == 40
    assert all(character in "0123456789abcdef" for character in value)
