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

$referenceEvaluation = Resolve-LatestFile -Pattern (Join-Path $WorkRoot "rebuild-01\full\fidelity-evaluation-resumed-*.json") -Label "Baseline fidelity evaluation"
$evaluation = Get-Content -LiteralPath $referenceEvaluation -Raw -Encoding UTF8 | ConvertFrom-Json
$bodyReferenceSha = [string]$evaluation.body_reference.sha256
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

[string[]]$labels = @("baseline", "refit1", "reconstruction2")
[string[]]$renders = @(
    (Resolve-LatestFile -Pattern (Join-Path $WorkRoot "rebuild-01\full\comparison-render-resumed-*\snapshots\fidelity-render-set.json") -Label "Baseline render set"),
    (Resolve-InputFile -Path (Join-Path $WorkRoot "rebuild-01\night-refinement-01\comparison-render\snapshots\fidelity-render-set.json") -Label "Refit 1 render set"),
    (Resolve-LatestFile -Pattern (Join-Path $WorkRoot "rebuild-02\full\comparison-render-fresh-*\snapshots\fidelity-render-set.json") -Label "Reconstruction 2 render set")
)

$head = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve BodyRig Git HEAD." }
$tag = $head.Substring(0, 8)
$outputRoot = Join-Path $WorkRoot ("silhouette-diagnostics-" + $tag)
if (Test-Path -LiteralPath $outputRoot) { throw "Silhouette diagnostic output already exists: $outputRoot" }
$stagingRoot = Join-Path $WorkRoot (".silhouette-diagnostics-$tag-" + [guid]::NewGuid().ToString("N") + ".tmp")
New-Item -ItemType Directory -Path $stagingRoot | Out-Null
$published = $false

try {
    $rows = @()
    for ($index = 0; $index -lt $renders.Count; $index++) {
        $label = $labels[$index]
        $outDir = Join-Path $stagingRoot $label
        Write-Host ""
        Write-Host "=== SILHOUETTE DIAGNOSTIC: $label ==="

        & $BodyRigPython -m bodyrig.silhouette_diagnostics_cli `
            --rig-setup (Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json") `
            --render-set $renders[$index] `
            --body-reference-rgba $bodyReference `
            --out-dir $outDir
        if ($LASTEXITCODE -ne 0) { throw "Silhouette diagnostic failed for $label." }

        $report = Get-Content -LiteralPath (Join-Path $outDir "silhouette-diagnostic.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        $rows += [pscustomobject]@{
            Candidate = $label
            Similarity = $report.profile_similarity
            HeadShoulder = $report.candidate.head_shoulder_ratio
            HeadShoulderScore = $report.candidate.head_shoulder_score
            Foreground = $report.candidate.mask.foreground_fraction
            BBoxAspect = $report.candidate.mask.bbox_aspect_width_over_height
            BBoxFill = $report.candidate.mask.bbox_fill_fraction
        }
    }

    Move-Item -LiteralPath $stagingRoot -Destination $outputRoot
    $published = $true

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "SILHOUETTE DIAGNOSTICS"
    Write-Host "============================================================"
    $rows | Format-Table -AutoSize
    Write-Host ""
    Write-Host "Inspect these mask/profile images if the ratios are implausible:"
    Write-Host $outputRoot
    Write-Host "============================================================"
}
finally {
    if (-not $published -and (Test-Path -LiteralPath $stagingRoot)) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
