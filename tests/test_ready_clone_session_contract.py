from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _launcher() -> str:
    return (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")


def test_ready_launcher_binds_exact_clean_bodyrig_checkout():
    text = _launcher()
    assert "$headRaw = @(& git -C $repoRoot rev-parse HEAD)" in text
    assert "if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1)" in text
    assert "$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()" in text
    assert "$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()" not in text
    assert text.count("git -C $repoRoot status --porcelain") >= 3
    assert "Could not bind physical clone session to BodyRig Git HEAD" in text
    assert "BodyRig checkout is dirty" in text
    assert '[switch]$AllowDirty' in text
    assert '"--bodyrig-revision", $head' in text
    assert '"--bodyrig-checkout-clean", $checkoutCleanText' in text
    assert '$checkoutCleanText = "true"' in text
    assert 'if (-not $checkoutClean)' in text
    assert "BodyRig Git HEAD changed during the physical clone session; refusing PASS evidence." in text
    assert "BodyRig checkout became dirty during the physical clone session; refusing PASS evidence." in text


def test_ready_launcher_binds_python_import_to_checkout_before_session_start():
    text = _launcher()
    expected = text.index('$expectedBodyRigModule = Resolve-InputFile')
    authority = text.index('$bodyRigAuthorityRaw = @(& $BodyRigPython -c')
    mismatch = text.index('BodyRig Python imports bodyrig from unexpected location')
    session_start = text.index("Invoke-SessionCommand -Arguments @(")

    assert 'bodyrig\\__init__.py' in text
    assert 'pathlib.Path(bodyrig.__file__).resolve()' in text
    assert "could not prove a single checkout-bound bodyrig import before physical session start" in text
    assert expected < authority < mismatch < session_start


def test_ready_launcher_rechecks_checkout_after_clone_before_pass():
    text = _launcher()
    clone = text.index("& $powerShellExe @cloneArgs")
    final_head = text.index("$finalHeadRaw = @(& git -C $repoRoot rev-parse HEAD)", clone)
    final_status = text.index("$finalDirty = @(& git -C $repoRoot status --porcelain)", final_head)
    dirty_reject = text.index("BodyRig checkout became dirty during the physical clone session; refusing PASS evidence.", final_status)
    session_pass = text.index('"pass",', dirty_reject)

    assert clone < final_head < final_status < dirty_reject < session_pass
    assert "Could not re-check BodyRig Git HEAD after physical clone." in text
    assert "Could not re-check BodyRig Git status after physical clone." in text
    assert "if ($finalDirty.Count -gt 0)" in text


def test_ready_launcher_rechecks_authority_after_pass_and_removes_stale_pass():
    text = _launcher()
    session_pass = text.index('"pass",')
    published = text.index("$sessionPassPublished = $true", session_pass)
    post_head = text.index("$postPassHeadRaw = @(& git -C $repoRoot rev-parse HEAD)", published)
    post_status = text.index("$postPassDirty = @(& git -C $repoRoot status --porcelain)", post_head)
    post_rig = text.index("$postPassRigSetupHash = (Get-FileHash", post_status)
    pass_banner = text.index('Write-Host "BodyRig ready-rig Stash clone: PASS"', post_rig)
    cleanup_gate = text.index("if ($sessionPassPublished)", pass_banner)
    cleanup = text.index("Remove-Item -LiteralPath $SessionReport -Force", cleanup_gate)

    assert session_pass < published < post_head < post_status < post_rig < pass_banner < cleanup_gate < cleanup
    assert "$sessionPassPublished = $false" in text
    assert "BodyRig Git HEAD changed after physical clone PASS publication; removing non-authoritative PASS evidence." in text
    assert "BodyRig checkout became dirty after physical clone PASS publication; removing non-authoritative PASS evidence." in text
    assert "BodyRig rig setup report changed after physical clone PASS publication; removing non-authoritative PASS evidence." in text
    assert "BodyRig removed non-authoritative physical clone PASS evidence" in text


def test_ready_launcher_binds_live_readiness_before_clone():
    text = _launcher()
    readiness = text.index("& $powerShellExe @readinessArgs")
    readiness_hash = text.index("$readinessHash = (Get-FileHash")
    readiness_binding = text.index('"readiness-pass"')
    clone = text.index("& $powerShellExe @cloneArgs")
    session_pass = text.index('"pass",', readiness_binding)

    assert '"-Out", $readinessReport' in text
    assert readiness < readiness_hash < readiness_binding < clone < session_pass


def test_ready_launcher_keeps_sensitive_stash_values_out_of_session_command():
    text = _launcher()
    start = text.index("Invoke-SessionCommand -Arguments @(")
    end = text.index(") -Step \"Physical clone session start\"", start)
    session_start = text[start:end]

    assert "StashUrl" not in session_start
    assert "ApiKeyEnv" not in session_start
    assert "STASH_API_KEY" not in session_start
    assert "Source" not in session_start
