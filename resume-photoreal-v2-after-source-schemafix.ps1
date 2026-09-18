param(
    [Parameter(Mandatory = $true)][string]$SourceRun,
    [Parameter(Mandatory = $true)][string]$ProjectionAuthority,
    [string]$PerformerId = "42",
    [string]$StashUrl = "",
    [string]$ApiKeyEnv = "STASH_API_KEY",
    [string]$RunRoot = "",
    [string]$ModelRoot = "",
    [string]$BodyRigPython = "",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$VisionDevice = "cuda:0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$baseScript = Join-Path $repoRoot "resume-photoreal-v2-after-source.ps1"
if (-not (Test-Path -LiteralPath $baseScript -PathType Leaf)) {
    throw "Base resume script not found: $baseScript"
}

$text = Get-Content -LiteralPath $baseScript -Raw -Encoding UTF8

$oldPathMap = @'
$pathMap = Read-Json -Path $sourcePathMap -Label "Verified source path map"
if ([string]$pathMap.format -ne "bodyrig-local-stash-path-map" -or [string]$pathMap.status -ne "PASS" -or [string]$pathMap.performer_id -ne $PerformerId -or -not (Test-StrictBoolean -Value $pathMap.production_activation -Expected $false)) {
    throw "Verified source path map is invalid."
}
'@

$newPathMap = @'
$pathMap = Read-Json -Path $sourcePathMap -Label "Verified source path map"
$pathMapPerformers = @($pathMap.performer_ids | ForEach-Object { [string]$_ })
if (
    [string]$pathMap.format -ne "bodyrig-local-stash-path-map" -or
    [int]$pathMap.version -ne 2 -or
    $pathMapPerformers.Count -ne 1 -or
    $pathMapPerformers[0] -ne $PerformerId -or
    $null -eq $pathMap.mapping -or
    $null -eq $pathMap.proof -or
    [string]::IsNullOrWhiteSpace([string]$pathMap.stash_origin) -or
    [string]::IsNullOrWhiteSpace([string]$pathMap.updated_utc)
) {
    throw "Verified source path map persisted schema is invalid."
}
'@

$oldSpatialProbe = @'
$spatialProbe = Read-Json -Path $sourceSpatialProbe -Label "Verified spatial metadata probe"
if ([string]$spatialProbe.format -ne "bodyrig-photoreal-spatial-container-probe" -or [string]$spatialProbe.status -ne "PASS" -or [string]$spatialProbe.performer_id -ne $PerformerId -or -not (Test-StrictBoolean -Value $spatialProbe.diagnostic_only -Expected $true) -or -not (Test-StrictBoolean -Value $spatialProbe.production_activation -Expected $false)) {
    throw "Verified spatial metadata probe is invalid."
}
'@

$newSpatialProbe = @'
$spatialProbe = Read-Json -Path $sourceSpatialProbe -Label "Verified spatial metadata probe"
if (
    [string]$spatialProbe.format -ne "bodyrig-photoreal-spatial-container-probe" -or
    -not (Test-NumericV1 -Value $spatialProbe.version) -or
    [string]$spatialProbe.performer_id -ne $PerformerId -or
    -not (Test-StrictBoolean -Value $spatialProbe.diagnostic_only -Expected $true) -or
    -not (Test-StrictBoolean -Value $spatialProbe.deprojection_authority -Expected $false) -or
    -not (Test-StrictBoolean -Value $spatialProbe.photoreal_acceptance_authority -Expected $false) -or
    -not (Test-StrictBoolean -Value $spatialProbe.build_only -Expected $true) -or
    -not (Test-StrictBoolean -Value $spatialProbe.runtime_dependency -Expected $false) -or
    -not (Test-StrictBoolean -Value $spatialProbe.production_activation -Expected $false)
) {
    throw "Verified spatial metadata probe persisted schema is invalid."
}
'@

if (-not $text.Contains($oldPathMap)) {
    throw "Base resume script path-map validator no longer matches the expected buggy revision."
}
if (-not $text.Contains($oldSpatialProbe)) {
    throw "Base resume script spatial-probe validator no longer matches the expected buggy revision."
}

$text = $text.Replace($oldPathMap, $newPathMap)
$text = $text.Replace($oldSpatialProbe, $newSpatialProbe)

$repoLiteral = "'" + $repoRoot.Replace("'", "''") + "'"
$oldRepoRoot = '$repoRoot = (Resolve-Path $PSScriptRoot).Path'
$newRepoRoot = '$repoRoot = (Resolve-Path -LiteralPath ' + $repoLiteral + ').Path'
if (-not $text.Contains($oldRepoRoot)) {
    throw "Base resume script repository-root binding was not found."
}
$text = $text.Replace($oldRepoRoot, $newRepoRoot)

$tempScript = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-photoreal-resume-schemafix-" + [Guid]::NewGuid().ToString("N") + ".ps1")
$text | Set-Content -LiteralPath $tempScript -Encoding UTF8

try {
    $argsMap = @{
        SourceRun = $SourceRun
        ProjectionAuthority = $ProjectionAuthority
        PerformerId = $PerformerId
        ApiKeyEnv = $ApiKeyEnv
        Distribution = $Distribution
        LinuxPython = $LinuxPython
        VisionDevice = $VisionDevice
    }
    if (-not [string]::IsNullOrWhiteSpace($StashUrl)) { $argsMap.StashUrl = $StashUrl }
    if (-not [string]::IsNullOrWhiteSpace($RunRoot)) { $argsMap.RunRoot = $RunRoot }
    if (-not [string]::IsNullOrWhiteSpace($ModelRoot)) { $argsMap.ModelRoot = $ModelRoot }
    if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) { $argsMap.BodyRigPython = $BodyRigPython }

    & $tempScript @argsMap
    exit $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}
