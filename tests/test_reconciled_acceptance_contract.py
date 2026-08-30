from pathlib import Path


def test_reconciled_acceptance_is_narrow_and_preserves_original_fail() -> None:
    script = Path("accept-reconciled-physical-clone.ps1").read_text(encoding="utf-8")

    assert 'BodyRig checkout became dirty during the physical clone session; refusing PASS evidence.' in script
    assert 'python-bytecode-postflight-false-negative' in script
    assert '".gitignore"' in script
    assert '"tests/test_repository_hygiene.py"' in script
    assert '"accept-reconciled-physical-clone.ps1"' in script
    assert '"tests/test_reconciled_acceptance_contract.py"' in script
    assert 'merge-base --is-ancestor' in script
    assert 'diff --name-status' in script
    assert '__pycache__/' in script
    assert '*.py[cod]' in script
    assert 'test_repository_hygiene.py' in script
    assert 'original_session_preserved = $true' in script
    assert 'recovery_rerun = $false' in script
    assert 'Copy-Item -LiteralPath $SessionReport -Destination $sessionCopy -Force' in script
    assert 'bodyrig-physical-clone-reconciliation.json' in script
    assert 'reconciliation_sha256' in script
    assert 'source_bodyrig_revision' in script
    assert 'reconciled' in script
    assert 'Recovery rerun:        NO' in script


def test_reconciled_acceptance_refuses_non_bytecode_observations() -> None:
    script = Path("accept-reconciled-physical-clone.ps1").read_text(encoding="utf-8")

    assert "__pycache__/[^/]+\\.pyc$" in script
    assert 'Observed dirty path is outside the approved Python bytecode failure class' in script
    assert 'Revision delta is broader than the approved Python-bytecode hygiene/reconciliation fix' in script
    assert 'Original session failure is not the bytecode-only postflight failure class' in script
