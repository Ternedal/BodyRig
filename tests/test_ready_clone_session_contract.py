from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _launcher() -> str:
    return (ROOT / "clone-body-from-stash-ready.ps1").read_text(encoding="utf-8")


def test_ready_launcher_binds_exact_clean_bodyrig_checkout():
    text = _launcher()
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert "git -C $repoRoot status --porcelain" in text
    assert "Could not bind physical clone session to BodyRig Git HEAD" in text
    assert "BodyRig checkout is dirty" in text
    assert '[switch]$AllowDirty' in text
    assert '"--bodyrig-revision", $head' in text
    assert '"--bodyrig-checkout-clean", $checkoutCleanText' in text
    assert "BodyRig Git HEAD changed during the physical clone session; refusing PASS evidence." in text


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
