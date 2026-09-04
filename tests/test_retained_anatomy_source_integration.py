from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_FITTER = ROOT / "bodyrig" / "external_fitter_cli.py"
CLONE_SCRIPT = ROOT / "clone-body.ps1"


def test_builtin_sith_binds_geometry_before_package_then_publishes_minimal_anatomy_source() -> None:
    source = EXTERNAL_FITTER.read_text(encoding="utf-8")

    geometry_gate = source.index('if config["adapter"] == BUILTIN_SITH_ADAPTER:')
    geometry_bind = source.index("avatar_vrm = bind_sith_body_geometry_authority(", geometry_gate)
    package_build = source.index("build_package(", geometry_bind)
    retention_gate = source.index('if config["adapter"] == BUILTIN_SITH_ADAPTER:', package_build)
    publish = source.index("publish_retained_anatomy_source(", retention_gate)

    assert 'BUILTIN_SITH_ADAPTER = "sith-smplx-vrm"' in source
    assert 'RETAINED_ANATOMY_DIRNAME = "retained-anatomy-source"' in source
    assert "output.parent / RETAINED_ANATOMY_DIRNAME" in source
    assert geometry_gate < geometry_bind < package_build < retention_gate < publish


def test_custom_fitters_do_not_implicitly_retain_private_workspace() -> None:
    source = EXTERNAL_FITTER.read_text(encoding="utf-8")

    assert source.count('if config["adapter"] == BUILTIN_SITH_ADAPTER:') >= 2
    assert "bind_sith_body_geometry_authority(" in source
    assert "publish_retained_anatomy_source(" in source
    assert "KeepPrivateWorkspace" not in source


def test_clone_still_deletes_full_private_workspace_only_after_fitter_returns_success() -> None:
    source = CLONE_SCRIPT.read_text(encoding="utf-8")

    fitter = source.index('Invoke-Checked -Executable $BodyRigPython -Arguments $fitArgs -Step "High-fidelity avatar fitting"')
    success = source.index("$success = $true", fitter)
    cleanup = source.index("Private identity workspace deleted after successful package build.", success)

    assert fitter < success < cleanup
    assert 'if ($success -and -not $KeepPrivateWorkspace' in source
