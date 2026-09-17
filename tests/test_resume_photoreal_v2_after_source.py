from __future__ import annotations

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "resume-photoreal-v2-after-source.ps1"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_resume_skips_expensive_source_stages() -> None:
    text = _script()

    assert "photoreal-stash-inventory.ps1" not in text
    assert "photoreal_dataset_plan_cli" not in text
    assert "photoreal_source_verify_cli" not in text
    assert 'source_rehash_skipped_explicitly = $true' in text
    assert 'resume_stage = 4' in text


def test_resume_binds_projection_authority_before_stage_four() -> None:
    text = _script()

    authority_binding = text.index(
        '[Environment]::SetEnvironmentVariable("BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY", $ProjectionAuthority, "Process")'
    )
    stage_four = text.index('"4/16 DETERMINISTIC SCOUT PLAN"')

    assert authority_binding < stage_four
    assert '"--plan", $PlanPath' in text
    assert '"--receipt", $ReceiptPath' in text


def test_resume_path_is_noninteractive_and_preserves_authority_boundaries() -> None:
    text = _script()

    assert "Read-Host" not in text
    assert "Pause" not in text
    assert 'photoreal_acceptance_authority = $false' in text
    assert 'production_activation = $false' in text
    assert 'human_visual_acceptance_required = $true' in text
