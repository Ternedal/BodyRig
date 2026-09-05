param(
    [switch]$RequireQuestConnected,
    [string]$Serial = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig high-fidelity physical run requires Windows."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}

$minimumPhysicalHandoffRevision = "ed3bb6cd0329b26fc4771ed7bda02964b42e9fa7"

function Need-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Assert-MinimumPhysicalHandoffRevision {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$CurrentHead,
        [Parameter(Mandatory = $true)][string]$MinimumRevision
    )
    $anchorSpec = $MinimumRevision + "^{commit}"
    & git -C $RepoRoot cat-file -e $anchorSpec 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "BodyRig checkout does not contain minimum safe high-fidelity physical handoff revision $MinimumRevision. Update the integration checkout before physical acceptance."
    }
    & git -C $RepoRoot merge-base --is-ancestor $MinimumRevision $CurrentHead
    if ($LASTEXITCODE -ne 0) {
        throw "BodyRig checkout revision $CurrentHead predates minimum safe high-fidelity physical handoff revision $MinimumRevision. Update the integration checkout before physical acceptance."
    }
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headLines = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
$head = ([string]$headLines[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "Current BodyRig Git revision is not canonical." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig checkout cleanliness." }
if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; clean/shelve local changes before physical acceptance." }
Assert-MinimumPhysicalHandoffRevision -RepoRoot $repoRoot -CurrentHead $head -MinimumRevision $minimumPhysicalHandoffRevision

$pythonCandidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $pythonCandidate -PathType Leaf) {
    $pythonExe = (Resolve-Path -LiteralPath $pythonCandidate).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) { throw "BodyRig Python was not found." }
    $pythonExe = $pythonCommand.Source
}
$versionText = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '^(\d+)\.(\d+)$') { throw "Could not verify BodyRig Python." }
if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 11)) {
    throw "BodyRig physical acceptance requires Python 3.11+; detected $versionText."
}
$expectedModule = Need-File (Join-Path $repoRoot "bodyrig\__init__.py") "BodyRig checkout module"
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    $moduleLines = @(& $pythonExe -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) { throw "BodyRig Python could not prove imported module authority." }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from a different checkout/package: $actualModule"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

$rendererReadinessScript = Need-File (Join-Path $repoRoot "check-reference-renderer-ready.ps1") "Canonical reference renderer readiness checker"
& $rendererReadinessScript

$contractPath = Need-File (Join-Path $repoRoot "reference-renderer\renderer-contract.json") "Reference renderer contract"
try { $contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json }
catch { throw "Reference renderer contract is invalid JSON: $contractPath" }
if ([string]$contract.format -ne "bodyrig-reference-renderer-contract" -or [int]$contract.version -ne 1) {
    throw "Unsupported reference renderer contract."
}
$unityVersion = ([string]$contract.unity_editor_version).Trim()
$univrmVersion = ([string]$contract.univrm_version).Trim()
if ([string]::IsNullOrWhiteSpace($unityVersion) -or [string]::IsNullOrWhiteSpace($univrmVersion)) {
    throw "Reference renderer contract lacks pinned Unity/UniVRM versions."
}
$unityExe = "C:\Program Files\Unity\Hub\Editor\$unityVersion\Editor\Unity.exe"
$unityExe = Need-File $unityExe "Pinned Unity $unityVersion editor"
$androidPlayer = Join-Path (Split-Path -Parent $unityExe) "Data\PlaybackEngines\AndroidPlayer"
if (-not (Test-Path -LiteralPath $androidPlayer -PathType Container)) {
    throw "Unity $unityVersion Android Build Support is missing: $androidPlayer"
}
$adbCandidate = Join-Path $androidPlayer "SDK\platform-tools\adb.exe"
$adbExe = Need-File $adbCandidate "Pinned Unity Android adb"

foreach ($relative in @(
    "check-reference-renderer-ready.ps1",
    "prepare-high-fidelity-physical-acceptance.ps1",
    "high-fidelity-physical-status.ps1",
    "run-reference-windows-renderer-probe.ps1",
    "record-reference-renderer-acceptance.ps1",
    "run-reference-quest-renderer-probe.ps1",
    "complete-reference-acceptance.ps1",
    "run-windows-renderer-probe.ps1",
    "record-renderer-acceptance.ps1",
    "run-quest-renderer-probe.ps1",
    "complete-acceptance.ps1",
    "reference-renderer\build-reference-renderer.ps1",
    "reference-renderer\Packages\manifest.json",
    "reference-renderer\ProjectSettings\ProjectVersion.txt"
)) {
    [void](Need-File (Join-Path $repoRoot $relative) "Canonical operator dependency")
}

$deviceLines = @(& $adbExe devices 2>&1)
if ($LASTEXITCODE -ne 0) { throw "adb devices failed: $($deviceLines -join [Environment]::NewLine)" }
$online = @($deviceLines | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device$' })
$quest = @()
foreach ($line in $online) {
    $candidateSerial = ($line -split '\s+')[0]
    if (-not [string]::IsNullOrWhiteSpace($Serial) -and $candidateSerial -ne $Serial) { continue }
    $modelLines = @(& $adbExe -s $candidateSerial shell getprop ro.product.model 2>&1)
    if ($LASTEXITCODE -eq 0) {
        $model = ($modelLines -join "").Trim()
        if ($model -match '(?i)(quest|oculus)') {
            $quest += [pscustomobject]@{ Serial = $candidateSerial; Model = $model }
        }
    }
}
if ($RequireQuestConnected) {
    if (-not [string]::IsNullOrWhiteSpace($Serial) -and $quest.Count -ne 1) {
        throw "Requested Quest serial '$Serial' is not an online Quest/Oculus adb device."
    }
    if ([string]::IsNullOrWhiteSpace($Serial) -and $quest.Count -ne 1) {
        throw "Expected exactly one online Quest/Oculus adb device; found $($quest.Count). Connect one headset or pass -Serial."
    }
}

Write-Host "BodyRig high-fidelity rig preflight: PASS"
Write-Host "Revision:       $head (clean)"
Write-Host "Handoff floor:  $minimumPhysicalHandoffRevision (ancestor)"
Write-Host "PowerShell:     $($PSVersionTable.PSVersion)"
Write-Host "Python:         $versionText | $pythonExe"
Write-Host "Unity:          $unityVersion | $unityExe"
Write-Host "UniVRM:         $univrmVersion"
Write-Host "Android module: $androidPlayer"
Write-Host "adb:            $adbExe (pinned Unity SDK)"
if ($quest.Count -eq 0) {
    Write-Host "Quest adb:      not currently connected (allowed unless -RequireQuestConnected was requested)"
} else {
    foreach ($device in $quest) { Write-Host "Quest adb:      $($device.Serial) | $($device.Model)" }
}
Write-Host "No acceptance evidence was created or modified."
exit 0
