from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run-photoreal-v2-p3-quest2-reference-probe.ps1"
PROBE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigP3Quest2Probe.cs"
BOOTSTRAP = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs"


def test_p3_reference_probe_requires_exact_device_handoff_lineage() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "p3_device_runtime_review_plan_sha256" in source
    assert "staged_student_hashes_roundtrip_verified" in source
    assert "P3 Quest2 handoff artifact differs from runtime plan" in source


def test_p3_reference_probe_uses_canonical_renderer_and_pinned_adb() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "reference-renderer\\renderer-contract.json" in source
    assert "reference-renderer\\build-reference-renderer.ps1" in source
    assert "PlaybackEngines\\AndroidPlayer\\SDK\\platform-tools" in source
    assert 'Platform = "Quest"' in source
    assert "refuses non-pinned adb" in source


def test_p3_reference_probe_is_explicitly_blocked_on_missing_xr_authority() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    probe = PROBE.read_text(encoding="utf-8")
    assert 'PSObject.Properties["com.unity.xr.openxr"]' in runner
    assert "canonical-openxr-runtime-not-pinned" in runner
    assert "stereo_rendering_observed = false" in probe
    assert "vr_safe_frame_pacing_observed = false" in probe
    assert 'stereo_authority = "blocked-until-canonical-xr-runtime-is-pinned"' in probe


def test_p3_unity_probe_rehashes_all_artifacts_and_loads_real_vrm() -> None:
    source = PROBE.read_text(encoding="utf-8")
    assert "Sha256File(fullPath)" in source
    assert "actual.SetEquals(seen)" in source
    assert "Vrm10.LoadPathAsync" in source
    assert "ValidateHumanoid(animator)" in source
    assert "installed_student_hashes_verified_on_device = true" in source
    assert "runtime_loaded = true" in source
    assert "frame_time_sample_count" in source
    assert "refreshRateRatio.value" in source


def test_p3_bootstrap_requires_explicit_request_marker() -> None:
    source = BOOTSTRAP.read_text(encoding="utf-8")
    marker = 'Path.Combine(p3Root, "run-p3-probe.request")'
    manifest = 'Path.Combine(p3Root, "p3-runtime-manifest.json")'
    normal = 'Path.Combine(defaultRoot, "runtime", "runtime-manifest.json")'
    assert marker in source
    assert manifest in source
    assert source.index(marker) < source.index(normal)
    assert "BodyRigP3Quest2Probe" in source


def test_p3_reference_probe_never_grants_runtime_or_photoreal_authority() -> None:
    runner = RUNNER.read_text(encoding="utf-8")
    probe = PROBE.read_text(encoding="utf-8")
    for text in (runner, probe):
        assert "runtime_acceptance_authority" in text
        assert "photoreal_acceptance_authority" in text
        assert "production_activation" in text
    assert "runtime_acceptance_authority = false" in probe
    assert "photoreal_acceptance_authority = false" in probe
    assert "production_activation = false" in probe


def test_p3_reference_probe_runner_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
