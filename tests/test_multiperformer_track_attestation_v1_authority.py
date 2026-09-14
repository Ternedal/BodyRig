from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "record-photoidentity-multiperformer-track-attestation.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_multiperformer_track_attestation_uses_bool_safe_numeric_v1() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT
    assert "Test-V1Version $publicReview.version" in SCRIPT
    assert "Test-V1Version $receipt.version" in SCRIPT
    assert "[int]$publicReview.version" not in SCRIPT
    assert "[int]$receipt.version" not in SCRIPT


def test_prepared_review_v1_precedes_human_track_selection() -> None:
    public_read = SCRIPT.index("$publicReview = Get-Content -LiteralPath $publicReviewPath")
    contract = SCRIPT.index('bodyrig-photoidentity-multiperformer-track-review-candidates', public_read)
    version = SCRIPT.index("Test-V1Version $publicReview.version", contract)
    revision = SCRIPT.index("$publicReview.bodyrig_revision -ne $head", version)
    no_target = SCRIPT.index("$publicReview.target_track_selected -ne $false", revision)
    selection = SCRIPT.index("$selected = @($publicReview.tracks", no_target)
    human = SCRIPT.index("Human confirmation: TRUE", selection)
    assert public_read < contract < version < revision < no_target < selection < human


def test_receipt_v1_precedes_revision_track_and_attestation_trust() -> None:
    receipt_read = SCRIPT.index("$receipt = Get-Content -LiteralPath $receiptPath")
    contract = SCRIPT.index('bodyrig-photoidentity-multiperformer-track-attestation', receipt_read)
    version = SCRIPT.index("Test-V1Version $receipt.version", contract)
    binding = SCRIPT.index("$receipt.bodyrig_revision -ne $head", version)
    attested = SCRIPT.index("$receipt.human_identity_attested -ne $true", binding)
    receipt_sha = SCRIPT.index("$receiptSha = (Get-FileHash", attested)
    assert receipt_read < contract < version < binding < attested < receipt_sha


def test_human_attestation_preserves_identity_and_nonactivation_boundaries() -> None:
    for boundary in (
        "-ConfirmIdentity",
        "QualityNote must contain at least 10 non-whitespace characters",
        "git -C $repoRoot rev-parse HEAD",
        "git -C $repoRoot status --porcelain",
        "requires an exact clean BodyRig checkout",
        "BodyRig Python imports from a different checkout",
        "TrackCandidateId is not unique in prepared review",
        "Private review index does not uniquely bind TrackCandidateId",
        '"biometric_identity_inference_used"',
        '"generic_guessing_permitted"',
        '"target_isolated_source_authority"',
        '"photoidentity_source_evidence_authority"',
        '"reconstruction_permitted"',
        '"production_activation"',
        "$publicReview.$field -ne $false",
        "$receipt.$field -ne $false",
        "$receipt.track_candidate_id -ne $TrackCandidateId",
    ):
        assert boundary in SCRIPT


def test_multiperformer_track_attestation_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    escaped = str(SCRIPT_PATH.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{escaped}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ exit 20 }}
$fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-V1Version' }}, $true)
if ($null -eq $fn) {{ exit 21 }}
Invoke-Expression $fn.Extent.Text
if (-not (Test-V1Version 1)) {{ exit 31 }}
if (-not (Test-V1Version 1.0)) {{ exit 32 }}
if (Test-V1Version $true) {{ exit 33 }}
if (Test-V1Version $false) {{ exit 34 }}
if (Test-V1Version '1') {{ exit 35 }}
if (Test-V1Version $null) {{ exit 36 }}
if (Test-V1Version 2) {{ exit 37 }}
exit 0
"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
