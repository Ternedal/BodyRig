from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _clone() -> str:
    return (ROOT / "clone-body.ps1").read_text(encoding="utf-8")


def test_clone_snapshots_source_bytes_before_recovery_and_rechecks_at_identity_build():
    text = _clone()
    snapshot = text.index("from bodyrig.portable_identity import source_set_sha256")
    recovery = text.index('Invoke-Checked -Executable $BodyRigPython -Arguments $recoverArgs')
    capture = text.index('Invoke-Checked -Executable $BodyRigPython -Arguments $captureArgs')
    identity = text.index('Invoke-Checked -Executable $BodyRigPython -Arguments $portableIdentityArgs')
    assert snapshot < recovery < capture < identity
    assert '$sourceSnapshotArgs += $resolvedSources' in text
    assert '"--expected-source-set-sha256", $sourceSetSnapshot' in text
    assert "Could not create the pre-recovery source byte-set snapshot." in text


def test_clone_builds_portable_identity_after_recovery_and_visual_capture_before_fitting():
    text = _clone()
    recovery = text.index('Invoke-Checked -Executable $BodyRigPython -Arguments $recoverArgs')
    capture = text.index('Invoke-Checked -Executable $BodyRigPython -Arguments $captureArgs')
    identity = text.index('Invoke-Checked -Executable $BodyRigPython -Arguments $portableIdentityArgs')
    fitting = text.index('Invoke-Checked -Executable $BodyRigPython -Arguments $fitArgs')
    assert recovery < capture < identity < fitting
    assert '$portableIdentityArgs += $resolvedSources' in text
    assert '"--identity-profile", $identityPath' in text
    assert '"--requested-alias", $BodyId' in text
    assert '"--out", $portableIdentityPath' in text


def test_clone_keeps_operator_alias_filename_but_fitter_uses_canonical_identity_authority():
    text = _clone()
    assert '$packagePath = Join-Path $OutputDir "$BodyId.mrbody"' in text
    assert '"--body-id", $BodyId' in text
    assert '"--portable-identity", $portableIdentityPath' in text
    assert '$canonicalBodyId = [string]$portableIdentity.body_id' in text
    assert "Final .mrbody canonical body id mismatch." in text
    assert '[string]$validated.body_id -ne $canonicalBodyId' in text


def test_clone_requires_exactly_one_portable_identity_provenance_stage():
    text = _clone()
    assert 'identity_stages = [s for s in v.provenance["pipeline"] if s.get("stage") == "identity_content"]' in text
    assert '$identityStages.Count -ne 1' in text
    assert '[string]$identityStage.adapter -ne "bodyrig.portable_identity"' in text
    assert '[string]$identityStage.revision -ne $canonicalBodyId.Substring(7)' in text
    assert "Final .mrbody portable identity provenance mismatch." in text


def test_clone_portable_receipt_is_path_free_artifact_not_private_workspace_material():
    text = _clone()
    declaration = text.index('$portableIdentityPath = Join-Path $OutputDir "bodyrig-portable-identity.json"')
    cleanup = text.index('Remove-Item -LiteralPath $PrivateWorkspace')
    assert declaration < cleanup
    assert 'Write-Host "Portable identity: $portableIdentityPath"' in text
    assert '$PrivateWorkspace' not in text[text.index('$portableIdentityArgs = @('):text.index('$fitArgs = @(')]


def test_ready_stash_wrapper_delegates_identity_authority_to_exact_clone_pipeline():
    text = (ROOT / "clone-body-from-stash.ps1").read_text(encoding="utf-8")
    assert '"-File", $cloneScript' in text
    assert '"-BodyId", $BodyId' in text
    assert '"-OutputDir", $cloneOutput' in text
    assert '"-SourceOverrideManifest", $observationSegments' in text
