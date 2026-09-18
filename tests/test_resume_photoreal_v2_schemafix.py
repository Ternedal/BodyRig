from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "resume-photoreal-v2-after-source-schemafix.ps1"
BASE = ROOT / "resume-photoreal-v2-after-source.ps1"


def test_schemafix_targets_cli_summary_fields_not_present_in_persisted_files() -> None:
    text = FIX.read_text(encoding="utf-8")

    assert "$pathMap.status" in text
    assert "$pathMap.performer_id" in text
    assert "$spatialProbe.status" in text
    assert "$pathMapPerformers = @($pathMap.performer_ids" in text
    assert '"bodyrig-photoreal-spatial-container-probe"' in text
    assert "$spatialProbe.deprojection_authority" in text
    assert "$spatialProbe.build_only" in text
    assert "$spatialProbe.runtime_dependency" in text


def test_schemafix_runs_temp_copy_without_dirtying_repository() -> None:
    text = FIX.read_text(encoding="utf-8")

    assert "GetTempPath" in text
    assert "$text.Replace($oldRepoRoot, $newRepoRoot)" in text
    assert "Set-Content -LiteralPath $tempScript" in text
    assert "Remove-Item -LiteralPath $tempScript" in text
    assert "git add" not in text
    assert "git commit" not in text


def test_base_resume_still_skips_source_rehash() -> None:
    text = BASE.read_text(encoding="utf-8")

    assert "photoreal_source_verify_cli" not in text
    assert 'source_rehash_skipped_explicitly = $true' in text
    assert 'resume_stage = 4' in text
