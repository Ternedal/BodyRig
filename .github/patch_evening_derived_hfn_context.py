from pathlib import Path

root = Path(__file__).resolve().parents[1]
script_path = root / "run-fidelity-evening.ps1"
test_path = root / "tests" / "test_fidelity_evening_derived_hfn_context.py"
script = script_path.read_text(encoding="utf-8")

old = '''    [string]$UnityExe = "",\n    [string]$ExecutionContext = "",\n    [switch]$ExecuteNextAction,\n'''
new = '''    [string]$UnityExe = "",\n    [string]$ExecutionContext = "",\n    [string]$HfnRoot = "",\n    [string]$HfnPersonId = "",\n    [string]$HfnBodyRevision = "",\n    [switch]$ExecuteNextAction,\n'''
if script.count(old) != 1:
    raise SystemExit("evening HFN parameter anchor drifted")
script = script.replace(old, new, 1)

anchor = '''$currentFloorRunner = Need-File -Path (Join-Path $repoRoot "run-fidelity-evening-current-floor-review.ps1") -Label "Current-floor evening review runner"\n\n$runnerArgs = @{\n'''
insert = '''$currentFloorRunner = Need-File -Path (Join-Path $repoRoot "run-fidelity-evening-current-floor-review.ps1") -Label "Current-floor evening review runner"\n\n$hfnIdentityValues = @($HfnRoot,$HfnPersonId,$HfnBodyRevision)\n$hfnIdentityPresent = @($hfnIdentityValues | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }).Count\nif (-not [string]::IsNullOrWhiteSpace($ExecutionContext) -and $hfnIdentityPresent -gt 0) {\n    throw "ExecutionContext cannot be combined with HfnRoot/HfnPersonId/HfnBodyRevision."\n}\nif ($hfnIdentityPresent -ne 0 -and $hfnIdentityPresent -ne 3) {\n    throw "HfnRoot, HfnPersonId and HfnBodyRevision must be supplied together or omitted together."\n}\n$hasExplicitHfnIdentity = $hfnIdentityPresent -eq 3\n\n$runnerArgs = @{\n'''
if script.count(anchor) != 1:
    raise SystemExit("evening HFN input-validation anchor drifted")
script = script.replace(anchor, insert, 1)

old = '''$temporaryExecutionContext = ""\nif ([string]::IsNullOrWhiteSpace($ExecutionContext)) {\n    $temporaryExecutionContext = Join-Path $eveningRoot (".component-gap-execution-context.empty-" + [Guid]::NewGuid().ToString("N") + ".json")\n    [IO.File]::WriteAllText($temporaryExecutionContext, "{}", [Text.UTF8Encoding]::new($false))\n    $contextPath = $temporaryExecutionContext\n} else {\n    $contextPath = Need-File -Path $ExecutionContext -Label "Component-gap execution context"\n}\n'''
new = '''$temporaryExecutionContext = ""\nif ([string]::IsNullOrWhiteSpace($ExecutionContext)) {\n    if ($expectedActionId -eq "source-bound-hfn-continuation" -and $hasExplicitHfnIdentity) {\n        if ($physicalKind -ne "face-secondary-hair-eye-comparison") {\n            throw "Derived HFN execution context requires exact face-secondary comparison physical authority."\n        }\n        $comparisonPackagePath = Need-File -Path (Join-Path $physicalRoot "comparison\\face-secondary-hair-eye-comparison.mrbody") -Label "Final face-secondary comparison package"\n        if ((Sha256 $comparisonPackagePath) -ne $physicalPackageSha -or [string]$gap.package_sha256 -ne $physicalPackageSha) {\n            throw "Final face-secondary comparison package bytes differ from the component-gap package authority."\n        }\n        $resolvedHfnRoot = Need-Directory -Path $HfnRoot -Label "HFN authority root"\n        $hfnRenderDir = Join-Path $eveningRoot ("hfn-" + $selected + "\\render-review")\n        $hfnHumanReviewDir = Join-Path $eveningRoot ("hfn-" + $selected + "\\human-review")\n        $derivedContext = [ordered]@{\n            package_path = $comparisonPackagePath\n            hfn_root = $resolvedHfnRoot\n            person_id = $HfnPersonId.Trim()\n            body_revision = $HfnBodyRevision.Trim()\n            hfn_render_dir = $hfnRenderDir\n            hfn_human_review_dir = $hfnHumanReviewDir\n        }\n        $temporaryExecutionContext = Join-Path $eveningRoot (".component-gap-execution-context.hfn-" + [Guid]::NewGuid().ToString("N") + ".json")\n        [IO.File]::WriteAllText(\n            $temporaryExecutionContext,\n            ($derivedContext | ConvertTo-Json -Depth 10 -Compress),\n            [Text.UTF8Encoding]::new($false)\n        )\n        $contextPath = $temporaryExecutionContext\n    } elseif ($hasExplicitHfnIdentity) {\n        throw "HFN identity parameters are only valid when source-bound-hfn-continuation is the first qualified gap action."\n    } else {\n        $temporaryExecutionContext = Join-Path $eveningRoot (".component-gap-execution-context.empty-" + [Guid]::NewGuid().ToString("N") + ".json")\n        [IO.File]::WriteAllText($temporaryExecutionContext, "{}", [Text.UTF8Encoding]::new($false))\n        $contextPath = $temporaryExecutionContext\n    }\n} else {\n    $contextPath = Need-File -Path $ExecutionContext -Label "Component-gap execution context"\n}\n'''
if script.count(old) != 1:
    raise SystemExit("evening HFN context synthesis anchor drifted")
script = script.replace(old, new, 1)
script_path.write_text(script, encoding="utf-8", newline="\n")

test_path.write_text(r'''from pathlib import Path


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
''', encoding="utf-8", newline="\n")
