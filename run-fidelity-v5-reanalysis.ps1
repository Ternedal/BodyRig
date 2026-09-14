param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [string]$BodyRigPython = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-LatestFile {
    param([Parameter(Mandatory = $true)][string]$Pattern,[Parameter(Mandatory = $true)][string]$Label)
    $matches = @(Get-ChildItem -Path $Pattern -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if ($matches.Count -lt 1) { throw "$Label not found: $Pattern" }
    return $matches[0].FullName
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
Set-Location $repoRoot
$WorkRoot = (Resolve-Path -LiteralPath $WorkRoot).Path
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"

$head = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve BodyRig Git HEAD." }
$tag = $head.Substring(0, 8)

$referenceSet = Resolve-InputFile -Path (Join-Path $WorkRoot "references\reference-set.json") -Label "Frozen fidelity reference set"
$baselineEvaluation = Resolve-LatestFile -Pattern (Join-Path $WorkRoot "rebuild-01\full\fidelity-evaluation-resumed-*.json") -Label "Baseline fidelity evaluation"
$baselineEval = Get-Content -LiteralPath $baselineEvaluation -Raw -Encoding UTF8 | ConvertFrom-Json
$bodyReferenceSha = [string]$baselineEval.body_reference.sha256
if ($bodyReferenceSha -notmatch '^[0-9a-f]{64}$') { throw "Baseline evaluation does not contain a canonical body-reference SHA-256." }

$identityRoot = Join-Path $env:LOCALAPPDATA "BodyRig\identity-workspaces"
$bodyReferenceMatches = @(
    Get-ChildItem -LiteralPath $identityRoot -Directory -ErrorAction Stop |
        ForEach-Object {
            $candidate = Join-Path $_.FullName "identity-capture\primary-rgba.png"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $sha = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($sha -eq $bodyReferenceSha) { $candidate }
            }
        }
)
if ($bodyReferenceMatches.Count -ne 1) {
    throw "Expected exactly one private body reference matching $bodyReferenceSha; found $($bodyReferenceMatches.Count)."
}
$bodyReference = Resolve-InputFile -Path $bodyReferenceMatches[0] -Label "Private body reference"

$baselineRender = Resolve-LatestFile -Pattern (Join-Path $WorkRoot "rebuild-01\full\comparison-render-resumed-*\snapshots\fidelity-render-set.json") -Label "Baseline render set"
$refitRender = Resolve-InputFile -Path (Join-Path $WorkRoot "rebuild-01\night-refinement-01\comparison-render\snapshots\fidelity-render-set.json") -Label "Refit 1 render set"
$reconstruction2Render = Resolve-LatestFile -Pattern (Join-Path $WorkRoot "rebuild-02\full\comparison-render-fresh-*\snapshots\fidelity-render-set.json") -Label "Reconstruction 2 render set"

$outputRoot = Join-Path $WorkRoot "reanalysis-v5-$tag"
if (Test-Path -LiteralPath $outputRoot) { throw "V5 reanalysis output already exists: $outputRoot" }
New-Item -ItemType Directory -Path $outputRoot | Out-Null

$evaluations = @(
    Join-Path $outputRoot "iteration-01-baseline.json",
    Join-Path $outputRoot "iteration-02-refit1.json",
    Join-Path $outputRoot "iteration-03-reconstruction2.json"
)
$renders = @($baselineRender, $refitRender, $reconstruction2Render)

for ($index = 0; $index -lt $renders.Count; $index++) {
    $iteration = $index + 1
    Write-Host ""
    Write-Host "=== V5 EVALUATION $iteration/3 ==="
    & $BodyRigPython -m bodyrig.fidelity_evaluator_cli `
        --rig-setup (Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json") `
        --reference-set $referenceSet `
        --render-set $renders[$index] `
        --body-reference-rgba $bodyReference `
        --iteration $iteration `
        --out $evaluations[$index]
    if ($LASTEXITCODE -ne 0) { throw "V5 evaluation $iteration failed." }
}

$decision = Join-Path $outputRoot "convergence-decision.json"
Write-Host ""
Write-Host "=== V5 CONVERGENCE ==="
& $BodyRigPython -m bodyrig.fidelity_convergence_cli `
    $evaluations[0] `
    $evaluations[1] `
    $evaluations[2] `
    --out $decision `
    --max-iterations 8
if ($LASTEXITCODE -ne 0) { throw "V5 convergence failed." }

$rows = foreach ($path in $evaluations) {
    $evaluation = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    [pscustomobject]@{
        Iteration = $evaluation.measurement.iteration
        Overall = $evaluation.measurement.scores.overall
        Body = $evaluation.measurement.scores.body_silhouette
        Face = $evaluation.measurement.scores.face_appearance
        Hair = $evaluation.measurement.scores.hair_appearance
        Skin = $evaluation.measurement.scores.skin_material
        Photo = $evaluation.measurement.scores.photorealism
        Plausible = $evaluation.measurement.scores.human_plausibility
        HeadShoulder = $evaluation.plausibility.head_shoulder_ratio
        ShoulderDelta = $evaluation.shape_hint.shoulder_profile_delta
        HipDelta = $evaluation.shape_hint.hip_profile_delta
        Evaluator = $evaluation.measurement.evaluator.revision
    }
}

Write-Host ""
Write-Host "============================================================"
Write-Host "V5 - NEW COMPARISON"
Write-Host "============================================================"
$rows | Format-Table -AutoSize

$result = Get-Content -LiteralPath $decision -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "Best iteration: $($result.best_iteration)"
Write-Host "Best overall:   $($result.best_overall)"
Write-Host "State:          $($result.state)"
Write-Host "Strategy:       $($result.strategy)"
Write-Host "Next focus:     $($result.next_focus)"
Write-Host "Output:         $outputRoot"
Write-Host "============================================================"
