from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-evening.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_evening_exposes_only_explicit_hfn_identity_parameters() -> None:
    text = source()
    assert '[string]$HfnRoot = ""' in text
    assert '[string]$HfnPersonId = ""' in text
    assert '[string]$HfnBodyRevision = ""' in text
    assert 'HfnRoot, HfnPersonId and HfnBodyRevision must be supplied together or omitted together.' in text
    assert 'ExecutionContext cannot be combined with HfnRoot/HfnPersonId/HfnBodyRevision.' in text


def test_derived_hfn_context_uses_exact_final_face_secondary_package() -> None:
    text = source()
    assert '$expectedActionId -eq "source-bound-hfn-continuation"' in text
    assert '$physicalKind -ne "face-secondary-hair-eye-comparison"' in text
    assert 'comparison\\face-secondary-hair-eye-comparison.mrbody' in text
    assert '(Sha256 $comparisonPackagePath) -ne $physicalPackageSha' in text
    assert '[string]$gap.package_sha256 -ne $physicalPackageSha' in text
    assert 'Final face-secondary comparison package bytes differ from the component-gap package authority.' in text


def test_derived_hfn_context_contains_exact_six_executor_fields() -> None:
    text = source()
    start = text.index('$derivedContext = [ordered]@{')
    end = text.index('}', start)
    block = text[start:end]
    expected = {
        'package_path = $comparisonPackagePath',
        'hfn_root = $resolvedHfnRoot',
        'person_id = $HfnPersonId.Trim()',
        'body_revision = $HfnBodyRevision.Trim()',
        'hfn_render_dir = $hfnRenderDir',
        'hfn_human_review_dir = $hfnHumanReviewDir',
    }
    for line in expected:
        assert line in block
    for forbidden in ('capture_id', 'uv_evidence', 'CaptureId', 'UvEvidence'):
        assert forbidden not in block


def test_hfn_render_and_review_paths_are_evening_local_and_deterministic() -> None:
    text = source()
    assert '$hfnRenderDir = Join-Path $eveningRoot ("hfn-" + $selected + "\\render-review")' in text
    assert '$hfnHumanReviewDir = Join-Path $eveningRoot ("hfn-" + $selected + "\\human-review")' in text
    assert 'Need-Directory -Path $HfnRoot -Label "HFN authority root"' in text


def test_hfn_identity_parameters_are_rejected_for_non_hfn_first_action() -> None:
    text = source()
    assert 'HFN identity parameters are only valid when source-bound-hfn-continuation is the first qualified gap action.' in text


def test_temporary_derived_context_is_removed_on_all_paths() -> None:
    text = source()
    assert '.component-gap-execution-context.hfn-' in text
    assert 'finally {' in text
    assert 'Remove-Item -LiteralPath $temporaryExecutionContext -Force -ErrorAction SilentlyContinue' in text


def test_evening_still_does_not_synthesize_capture_or_uv_selection() -> None:
    text = source()
    assert 'CaptureId <' not in text
    assert 'UvEvidence <' not in text
    assert 'hfncap-' not in text
    assert 'hfncand-' not in text
