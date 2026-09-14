from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_does_not_expose_redundant_hfn_identity_inputs() -> None:
    text = source()
    assert '[string]$HfnRoot = ""' not in text
    assert '[string]$HfnPersonId = ""' not in text
    assert '[string]$HfnBodyRevision = ""' not in text
    assert '[string]$ExecutionContext = ""' in text


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


def test_evening_auto_resolves_identity_from_source_current_floor_authority() -> None:
    text = source()
    assert "function Resolve-HfnIdentityBinding" in text
    assert "-m bodyrig.hfn_identity_binding" in text
    assert '-BodyId ([string]$gap.body_id)' in text
    assert '-SourcePackageSha $currentFloorPackageSha' in text
    assert '-SourcePackageSha $physicalPackageSha' not in text
    assert '[string]$binding.source_package_sha256 -ne $SourcePackageSha' in text
    assert '$binding.source_authority_required -ne $true' in text
    assert '$binding.production_activation -ne $false' in text


def test_derived_hfn_context_is_bound_to_exact_final_face_secondary_package() -> None:
    text = source()
    assert '$physicalKind -ne "face-secondary-hair-eye-comparison"' in text
    assert 'comparison\\face-secondary-hair-eye-comparison.mrbody' in text
    assert '(Sha256 $hfnPackagePath) -ne $physicalPackageSha' in text
    assert "package bytes differ from the final component-gap package authority" in text
    assert 'package_path = $hfnPackagePath' in text


def test_unique_identity_match_populates_context_and_outputs_are_deterministic() -> None:
    text = source()
    assert '$hfnIdentityMatch = @($hfnIdentity.matches)[0]' in text
    assert '$contextFields.person_id = ([string]$hfnIdentityMatch.person_id).Trim()' in text
    assert '$contextFields.body_revision = ([string]$hfnIdentityMatch.body_revision).Trim()' in text
    assert 'hfn_root = $hfnRootPath' in text
    assert '$hfnTag = $physicalPackageSha.Substring(0, 12)' in text
    assert 'hfn_render_dir = (Join-Path $eveningRoot "hfn-render-$selected-$hfnTag")' in text
    assert 'hfn_human_review_dir = (Join-Path $eveningRoot "hfn-human-review-$selected-$hfnTag")' in text


def test_non_unique_identity_stays_operator_controlled_without_guessing() -> None:
    text = source()
    assert '$state -notin @("resolved", "unresolved", "blocked", "ambiguous")' in text
    assert 'if ([string]$hfnIdentity.state -eq "resolved")' in text
    assert "HFN identity auto-resolution stopped fail-closed" in text
    resolved = text.index('if ([string]$hfnIdentity.state -eq "resolved")')
    person_assignment = text.index('$contextFields.person_id =', resolved)
    else_pos = text.index('} else {', person_assignment)
    assert resolved < person_assignment < else_pos
    blocked_segment = text[else_pos:text.index('$derivedContextJson =', else_pos)]
    assert '$contextFields.person_id' not in blocked_segment
    assert '$contextFields.body_revision' not in blocked_segment


def test_execution_context_remains_explicit_expert_override() -> None:
    text = source()
    assert '$contextPath = Need-File -Path $ExecutionContext -Label "Component-gap execution context"' in text
    assert 'if ([string]::IsNullOrWhiteSpace($ExecutionContext))' in text


def test_evening_does_not_synthesize_hfn_capture_or_uv_evidence() -> None:
    text = source()
    context_start = text.index('$contextFields = [ordered]@{')
    context_end = text.index('}', context_start)
    context = text[context_start:context_end]
    for forbidden in ("capture_id", "CaptureId", "uv_evidence", "UvEvidence", "hfncap-", "hfncand-"):
        assert forbidden not in context


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
