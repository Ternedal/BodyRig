from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _script() -> str:
    return (ROOT / "accept-physical-clone.ps1").read_text(encoding="utf-8")


def test_high_fidelity_gate_a_requires_exact_session_revision_and_clean_checkout():
    text = _script()
    assert '"pass"' in text and '"complete"' in text
    assert "bodyrig_checkout_clean -ne $true" in text
    assert "Current BodyRig HEAD does not match the physical clone session revision." in text
    assert "BodyRig checkout is dirty; high-fidelity Gate A requires the exact clean clone revision." in text
    assert "bodyrig.physical_session validate" in text


def test_high_fidelity_gate_a_binds_python_import_to_same_checkout_before_validation_or_output():
    text = _script()
    authority = text.index('import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())')
    validate = text.index("-m bodyrig.physical_session validate")
    output = text.index("New-Item -ItemType Directory -Path $OutputDir")
    assert authority < validate < output
    assert 'Join-Path $repoRoot "bodyrig\\__init__.py"' in text
    assert "BodyRig Python could not prove its imported bodyrig module authority." in text
    assert "BodyRig Python imports bodyrig from a different checkout/package:" in text
    assert "[System.StringComparison]::OrdinalIgnoreCase" in text


def test_high_fidelity_gate_a_binds_readiness_and_same_package_bytes():
    text = _script()
    assert "Readiness report SHA-256 no longer matches the physical clone session." in text
    assert "Rig setup SHA-256 differs between session and readiness evidence." in text
    assert "Copy-Exact $packageSource $packagePath" in text
    assert 'session_sha256 = (Sha256 $sessionCopy)' in text
    assert 'readiness_sha256 = (Sha256 $readinessCopy)' in text
    assert 'mode = "stash-sith-high-fidelity"' in text


def test_high_fidelity_gate_a_refuses_placeholder_or_non_sith_fit():
    text = _script()
    assert '[string]$packageInfo.fitting_adapter -ne "sith-smplx-vrm"' in text
    assert '[string]$packageInfo.fitting_revision -ne "1"' in text
    assert "Physical Gate A refuses a placeholder avatar" in text
    assert "visual_identity_provenance_matches" in text


def test_high_fidelity_gate_a_runs_and_binds_anatomical_skin_qa():
    text = _script()
    qa = text.index("-m bodyrig.skin_qa $packagePath --out $skinQaPath")
    materialize = text.index("-m bodyrig.materialize_cli $packagePath --out $runtimeDir")
    report = text.index('skin_qa = [ordered]@{')
    assert qa < materialize < report
    assert 'report_sha256 = $skinQaFile.Hash' in text
    assert 'structural_pass = $true' in text
    assert 'automated_assessment = $skinAssessment' in text
    assert 'manual_review_required = $true' in text
    assert "Anatomical skin QA is not bound to the accepted package." in text


def test_high_fidelity_gate_a_materializes_renderer_runtime_from_accepted_package():
    text = _script()
    copy_package = text.index("Copy-Exact $packageSource $packagePath")
    materialize = text.index("-m bodyrig.materialize_cli $packagePath --out $runtimeDir")
    report = text.index('format = "bodyrig-rig-acceptance"')
    assert copy_package < materialize < report
    assert 'manifest = "runtime/runtime-manifest.json"' in text
    assert 'physical_renderer_acceptance = "pending"' in text
    assert 'production_activation = $false' in text


def test_ready_launcher_defaults_physical_artifacts_outside_checkout():
    text = (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")
    assert 'BodyRig\\physical-clones\\$BodyId-$stamp-$runSuffix' in text
    assert 'BodyRig\\physical-clone-sessions\\$BodyId-$stamp-$runSuffix.json' in text
    assert 'Join-Path (Get-Location).Path "bodyrig-stash-' not in text
