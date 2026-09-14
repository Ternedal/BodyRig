from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_exposes_only_explicit_hfn_identity_authority() -> None:
    text = source()
    assert '[string]$HfnRoot = ""' not in text
    assert '[string]$HfnPersonId = ""' in text
    assert '[string]$HfnBodyRevision = ""' in text
    assert "HfnPersonId and HfnBodyRevision together" in text
    assert "partial identity authority is refused" in text


def test_evening_derives_hfn_root_from_exact_current_checkout_person_library() -> None:
    text = source()
    assert "function Resolve-CanonicalPersonLibrary" in text
    assert "$env:PYTHONPATH = $RepoRoot" in text
    assert "from bodyrig.storage import person_library" in text
    assert "bodyrig.__file__" in text
    assert '$expectedModulePath = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\\__init__.py"))' in text
    assert "did not import the exact current-checkout package" in text
    assert 'Need-Directory -Path $rootText -Label "Canonical BodyRig person library root"' in text
    assert '$hfnRootPath = Resolve-CanonicalPersonLibrary -Python $BodyRigPython -RepoRoot $repoRoot' in text
    assert "$env:PYTHONPATH = $previousPythonPath" in text


def test_derived_hfn_context_is_bound_to_exact_final_face_secondary_package() -> None:
    text = source()
    assert '$physicalKind -ne "face-secondary-hair-eye-comparison"' in text
    assert 'comparison\\face-secondary-hair-eye-comparison.mrbody' in text
    assert '(Sha256 $hfnPackagePath) -ne $physicalPackageSha' in text
    assert "package bytes differ from the final component-gap package authority" in text
    assert 'package_path = $hfnPackagePath' in text


def test_derived_hfn_context_uses_explicit_identity_and_deterministic_outputs() -> None:
    text = source()
    assert 'hfn_root = $hfnRootPath' in text
    assert 'person_id = $HfnPersonId.Trim()' in text
    assert 'body_revision = $HfnBodyRevision.Trim()' in text
    assert '$hfnTag = $physicalPackageSha.Substring(0, 12)' in text
    assert 'hfn_render_dir = (Join-Path $eveningRoot "hfn-render-$selected-$hfnTag")' in text
    assert 'hfn_human_review_dir = (Join-Path $eveningRoot "hfn-human-review-$selected-$hfnTag")' in text


def test_generic_and_derived_context_authorities_are_mutually_exclusive() -> None:
    text = source()
    assert "ExecutionContext cannot be combined with HfnPersonId/HfnBodyRevision" in text
    assert '$hfnExplicitCount -eq 2 -and $expectedActionId -ne "source-bound-hfn-continuation"' in text
    assert "Explicit HFN identity context is only valid when source-bound-hfn-continuation is the qualified next action." in text


def test_evening_does_not_synthesize_hfn_capture_or_uv_evidence() -> None:
    text = source()
    derived_start = text.index('$derivedContext = [ordered]@{')
    derived_end = text.index('}', derived_start)
    derived = text[derived_start:derived_end]
    for forbidden in ("capture_id", "CaptureId", "uv_evidence", "UvEvidence", "hfncap-", "hfncand-"):
        assert forbidden not in derived


def test_temporary_hfn_context_is_create_then_cleaned_by_existing_finally() -> None:
    text = source()
    assert '[IO.File]::WriteAllText($temporaryExecutionContext, $derivedContextJson' in text
    finally_pos = text.index('} finally {', text.index('$temporaryExecutionContext = ""'))
    cleanup_pos = text.index('Remove-Item -LiteralPath $temporaryExecutionContext -Force', finally_pos)
    assert cleanup_pos > finally_pos


def test_derived_context_preserves_one_step_executor_and_human_boundaries() -> None:
    text = source()
    assert '-Execute:$ExecuteNextAction' in text
    assert 'BODYRIG ONE QUALIFIED COMPONENT-GAP STEP EXECUTED' in text
    assert 'Rerun this evening command to recompute physical evidence before any further action.' in text
    assert 'record-high-fidelity-hfn-review.ps1' not in text
    assert 'record-high-fidelity-human-review.ps1' not in text

def test_temporary_context_creation_is_inside_cleanup_try() -> None:
    text = source()
    anchor = text.index('$temporaryExecutionContext = ""')
    try_pos = text.index('try {', anchor)
    derived_write_pos = text.index('[IO.File]::WriteAllText($temporaryExecutionContext, $derivedContextJson', anchor)
    empty_write_pos = text.index('[IO.File]::WriteAllText($temporaryExecutionContext, "{}"', anchor)
    finally_pos = text.index('} finally {', try_pos)
    cleanup_pos = text.index('Remove-Item -LiteralPath $temporaryExecutionContext -Force', finally_pos)
    assert try_pos < derived_write_pos < finally_pos
    assert try_pos < empty_write_pos < finally_pos
    assert cleanup_pos > finally_pos
