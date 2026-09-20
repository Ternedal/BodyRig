from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "resume-photoreal-v2-after-frame-index.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_stage16_remediation_reuses_completed_frame_analysis() -> None:
    text = _script()

    assert "bodyrig.photoreal_frame_index_cli" in text
    assert "bodyrig.photoreal_frame_analyzer_cli" not in text
    assert "bodyrig.photoreal_frame_identity_authority_cli" not in text
    assert '"frame-measurements.json"' in text
    assert '"frame-authorized-observations.json"' in text
    assert 'Write-Host "Frame re-analysis: NO"' in text
    assert 'Write-Host "Source rehash:     NO"' in text


def test_stage16_remediation_only_accepts_near_duplicate_only_block() -> None:
    text = _script()

    assert '$sourceBlockers.Count -ne 1' in text
    assert '"cross-split perceptual near-duplicates detected"' in text
    assert "automatic near-duplicate remediation is not sufficient" in text


def test_stage16_remediation_preserves_old_evidence_and_creates_new_root() -> None:
    text = _script()

    assert '"pre-remediation-frame-index.json"' in text
    assert '"pre-remediation-p0-status.json"' in text
    assert '"stage16-remediation-receipt.json"' in text
    assert '"resume16"' in text
    assert "Copy-Evidence" in text


def test_stage16_remediation_status_tracks_new_authority_without_crossing_production() -> None:
    text = _script()

    assert '"teacher-training-authorized"' in text
    assert "teacher_training_authorized = $trainingAuthorized" in text
    assert "human_visual_acceptance_required = $true" in text
    assert "photoreal_acceptance_authority = $false" in text
    assert "production_activation = $false" in text
    assert "resumed_from_stage16_run = $SourceRun" in text


def test_stage16_remediation_does_not_mix_cli_stdout_with_exit_code() -> None:
    text = _script()

    assert '$stageOutput = @(& $script:Python @Arguments 2>&1)' in text
    assert 'foreach ($line in $stageOutput) { Write-Host ([string]$line) }' in text
    assert 'return $code' in text
