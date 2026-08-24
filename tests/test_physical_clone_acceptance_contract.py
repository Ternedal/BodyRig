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
