param(
    [ValidateSet("Windows", "Quest")]
    [string]$Platform = "Windows",
    [string]$UnityExe = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-UnityEditor {
    param([string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        if (-not (Test-Path -LiteralPath $Requested -PathType Leaf)) { throw "Unity.exe not found: $Requested" }
        return (Resolve-Path -LiteralPath $Requested).Path
    }

    $hubRoot = "C:\Program Files\Unity\Hub\Editor"
    $pinned = Join-Path $hubRoot "6000.3.13f1\Editor\Unity.exe"
    if (Test-Path -LiteralPath $pinned -PathType Leaf) { return $pinned }
    if (-not (Test-Path -LiteralPath $hubRoot -PathType Container)) {
        throw "Unity Hub editor root not found. Install Unity 6.3 LTS or pass -UnityExe."
    }

    $candidates = @(Get-ChildItem -LiteralPath $hubRoot -Directory | Where-Object { $_.Name -match '^6000\.3\.(\d+)f(\d+)$' } | Sort-Object {
        $match = [regex]::Match($_.Name, '^6000\.3\.(\d+)f(\d+)$')
        ([int]$match.Groups[1].Value * 1000) + [int]$match.Groups[2].Value
    } -Descending)
    foreach ($candidate in $candidates) {
        $exe = Join-Path $candidate.FullName "Editor\Unity.exe"
        if (Test-Path -LiteralPath $exe -PathType Leaf) { return $exe }
    }
    throw "No Unity 6.3 LTS editor found under $hubRoot. Install it or pass -UnityExe."
}

$projectRoot = (Resolve-Path $PSScriptRoot).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot "..")).Path
$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve exact BodyRig Git HEAD before renderer build." }
$bodyRigRevision = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($bodyRigRevision -notmatch '^[0-9a-f]{40}$') { throw "BodyRig Git HEAD is not a canonical 40-character SHA." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness before renderer build." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; physical reference renderer must be built from an exact clean revision." }

$UnityExe = Resolve-UnityEditor $UnityExe
$method = if ($Platform -eq "Windows") { "BodyRig.ReferenceRenderer.Editor.BodyRigReferenceBuild.BuildWindowsBatch" } else { "BodyRig.ReferenceRenderer.Editor.BodyRigReferenceBuild.BuildQuestBatch" }
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = if ($Platform -eq "Windows") {
        Join-Path $projectRoot "Builds\Windows\BodyRigReferenceProbe.exe"
    } else {
        Join-Path $projectRoot "Builds\Quest\BodyRigReferenceProbe.apk"
    }
}
$Output = [System.IO.Path]::GetFullPath($Output)

Write-Host "BodyRig reference renderer build"
Write-Host "Unity:     $UnityExe"
Write-Host "Project:   $projectRoot"
Write-Host "Revision:  $bodyRigRevision"
Write-Host "Platform:  $Platform"
Write-Host "Output:    $Output"

& $UnityExe -batchmode -quit -projectPath $projectRoot -executeMethod $method -bodyrigOutput $Output -bodyrigRevision $bodyRigRevision -logFile -
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { throw "Unity BodyRig reference renderer build failed with exit code $exitCode" }
if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) { throw "Unity returned success but expected build output is missing: $Output" }

# Generated Unity build assets live under ignored Assets/BodyRigGenerated. The
# tracked checkout must nevertheless remain byte-for-byte clean after the build.
$dirtyAfter = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not re-check BodyRig checkout after renderer build." }
if ($dirtyAfter.Count -gt 0) { throw "Renderer build changed tracked/unignored BodyRig checkout state; refusing physical build evidence." }
$currentHead = ([string]@(& git -C $repoRoot rev-parse HEAD 2>&1)[0]).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $currentHead -ne $bodyRigRevision) { throw "BodyRig Git HEAD changed during renderer build." }

Write-Host "BodyRig reference renderer build: PASS | revision $bodyRigRevision"
Write-Host $Output
exit 0
