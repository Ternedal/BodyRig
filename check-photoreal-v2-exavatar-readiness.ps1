param(
    [string]$AssetRoot = "",
    [string]$ReferenceModelRoot = "",
    [ValidateSet("female","male","neutral")][string]$SmplxGender = "female",
    [ValidateSet("colmap","virtual")][string]$CameraMode = "colmap",
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxDependencyRoot = "/opt/bodyrig-exavatar/deps",
    [string]$LinuxRuntimePython = "/opt/bodyrig-exavatar/bin/python",
    [string]$LinuxMaterializerPython = "/opt/bodyrig-photoreal/bin/python",
    [string]$WslExe = "wsl.exe",
    [string]$Out = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-WslPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateSet("file","dir","executable")][string]$Kind
    )
    $flag = switch ($Kind) {
        "file" { "-f" }
        "dir" { "-d" }
        "executable" { "-x" }
    }
    & $WslExe -d $Distribution -- /usr/bin/test $flag $Path 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Convert-ToWslPath {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)
    $raw = @(& $WslExe -d $Distribution -- /usr/bin/wslpath -a -u $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$raw[0])) {
        throw "Could not translate Windows path into WSL: $WindowsPath"
    }
    return ([string]$raw[0]).Trim()
}

function Invoke-WslCapture {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $raw = @(& $WslExe -d $Distribution -- @Arguments 2>&1)
    $code = $LASTEXITCODE
    return [pscustomobject]@{
        exit_code = $code
        lines = @($raw | ForEach-Object { [string]$_ })
        text = (($raw | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "ExAvatar readiness doctor is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required." }
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "Distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxDependencyRoot) -or -not $LinuxDependencyRoot.StartsWith('/')) {
    throw "LinuxDependencyRoot must be an absolute Linux path."
}
if ([string]::IsNullOrWhiteSpace($LinuxRuntimePython) -or -not $LinuxRuntimePython.StartsWith('/')) {
    throw "LinuxRuntimePython must be an absolute Linux path."
}
if ([string]::IsNullOrWhiteSpace($LinuxMaterializerPython) -or -not $LinuxMaterializerPython.StartsWith('/')) {
    throw "LinuxMaterializerPython must be an absolute Linux path."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }

if ([string]::IsNullOrWhiteSpace($AssetRoot)) {
    $AssetRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\exavatar-assets"
}
if ([string]::IsNullOrWhiteSpace($ReferenceModelRoot)) {
    $ReferenceModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$AssetRoot = [IO.Path]::GetFullPath($AssetRoot)
$ReferenceModelRoot = [IO.Path]::GetFullPath($ReferenceModelRoot)

if ([string]::IsNullOrWhiteSpace($Out)) {
    $doctorRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\exavatar-readiness"
    New-Item -ItemType Directory -Path $doctorRoot -Force | Out-Null
    $Out = Join-Path $doctorRoot ("readiness-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
}
$Out = [IO.Path]::GetFullPath($Out)
if (Test-Path -LiteralPath $Out) { throw "ExAvatar readiness output already exists: $Out" }
$outParent = Split-Path -Parent $Out
if ([string]::IsNullOrWhiteSpace($outParent)) { throw "Out must have a parent directory." }
New-Item -ItemType Directory -Path $outParent -Force | Out-Null

$blockers = New-Object System.Collections.Generic.List[string]

$wslProbe = Invoke-WslCapture -Arguments @("/usr/bin/env","true")
$wslReady = $wslProbe.exit_code -eq 0
if (-not $wslReady) { $blockers.Add("WSL distribution is not callable: $Distribution") }

$nvidia = if ($wslReady) {
    Invoke-WslCapture -Arguments @("nvidia-smi","--query-gpu=index,name,memory.total,pci.bus_id,driver_version","--format=csv,noheader")
} else {
    [pscustomobject]@{ exit_code = 1; lines = @(); text = "" }
}
if ($nvidia.exit_code -ne 0 -or $nvidia.lines.Count -lt 1) {
    $blockers.Add("WSL NVIDIA passthrough returned no GPU.")
}

$nvcc = if ($wslReady) { Invoke-WslCapture -Arguments @("nvcc","--version") } else { [pscustomobject]@{ exit_code = 1; lines = @(); text = "" } }
$nvccReady = $nvcc.exit_code -eq 0
$nvccVersion = $null
if ($nvccReady -and $nvcc.text -match 'release\s+([0-9]+\.[0-9]+)') {
    $nvccVersion = $Matches[1]
}
if (-not $nvccReady) {
    $blockers.Add("nvcc is not available in WSL.")
} elseif ($nvccVersion -ne "12.4") {
    $blockers.Add("nvcc must report CUDA 12.4 for the pinned ExAvatar runtime; observed: $nvccVersion")
}

$publicReceipt = "$($LinuxDependencyRoot.TrimEnd('/'))/bodyrig-public-dependencies.json"
$runtimeRoot = $LinuxRuntimePython.Substring(0, $LinuxRuntimePython.LastIndexOf('/bin/python'))
$runtimeReceipt = "$runtimeRoot/bodyrig-exavatar-runtime-setup.json"

$publicReceiptReady = $wslReady -and (Test-WslPath -Path $publicReceipt -Kind file)
$runtimePythonReady = $wslReady -and (Test-WslPath -Path $LinuxRuntimePython -Kind executable)
$runtimeReceiptReady = $wslReady -and (Test-WslPath -Path $runtimeReceipt -Kind file)
$materializerPythonReady = $wslReady -and (Test-WslPath -Path $LinuxMaterializerPython -Kind executable)

if (-not $publicReceiptReady) { $blockers.Add("Pinned ExAvatar public dependency receipt is missing: $publicReceipt") }
if (-not $runtimePythonReady) { $blockers.Add("Pinned ExAvatar runtime Python is missing: $LinuxRuntimePython") }
if (-not $runtimeReceiptReady) { $blockers.Add("Pinned ExAvatar runtime receipt is missing: $runtimeReceipt") }
if (-not $materializerPythonReady) { $blockers.Add("Photoreal materializer Python is missing: $LinuxMaterializerPython") }

$strictPreflight = $null
$strictPreflightExit = $null
$preflightError = $null
$tempOutput = Join-Path $outParent (".exavatar-preflight-" + [Guid]::NewGuid().ToString("N") + ".json")
try {
    if ($wslReady) {
        $linuxRepo = Convert-ToWslPath -WindowsPath $repoRoot
        $linuxAssets = Convert-ToWslPath -WindowsPath $AssetRoot
        $linuxReference = Convert-ToWslPath -WindowsPath $ReferenceModelRoot
        $linuxTempOutput = Convert-ToWslPath -WindowsPath $tempOutput

        $preflightPython = if ($materializerPythonReady) { $LinuxMaterializerPython } elseif ($runtimePythonReady) { $LinuxRuntimePython } else { "/usr/bin/python3" }
        $args = @(
            "/usr/bin/env",
            "PYTHONPATH=$linuxRepo",
            "PYTHONNOUSERSITE=1",
            $preflightPython,
            "-m", "bodyrig.photoreal_exavatar_preflight_cli",
            "--dependency-root", $LinuxDependencyRoot,
            "--asset-root", $linuxAssets,
            "--reference-model-root", $linuxReference,
            "--smplx-gender", $SmplxGender,
            "--out", $linuxTempOutput
        )
        if ($CameraMode -eq "virtual") { $args += "--no-colmap" }

        $preflightRaw = @(& $WslExe -d $Distribution -- @args 2>&1)
        $strictPreflightExit = $LASTEXITCODE

        if (Test-Path -LiteralPath $tempOutput -PathType Leaf) {
            $strictPreflight = Get-Content -LiteralPath $tempOutput -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
            foreach ($item in @($strictPreflight.blockers)) {
                $text = ([string]$item).Trim()
                if (-not [string]::IsNullOrWhiteSpace($text)) { $blockers.Add($text) }
            }
        } elseif ($strictPreflightExit -ne 0) {
            $preflightError = (($preflightRaw | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
            $blockers.Add("Strict ExAvatar asset/code preflight could not produce a receipt.")
        }
    }
}
finally {
    if (Test-Path -LiteralPath $tempOutput -PathType Leaf) {
        Remove-Item -LiteralPath $tempOutput -Force -ErrorAction SilentlyContinue
    }
}

$uniqueBlockers = @($blockers | Sort-Object -Unique)
$missingRestricted = @()
$missingOtherAssets = @()
$repoIssues = @()
if ($null -ne $strictPreflight) {
    foreach ($asset in @($strictPreflight.assets)) {
        if ($asset.present -eq $true -and [int64]$asset.size_bytes -gt 0) { continue }
        $entry = [ordered]@{
            name = [string]$asset.name
            relative_path = [string]$asset.relative_path
            restricted_or_operator_supplied = [bool]$asset.restricted_or_operator_supplied
        }
        if ($asset.restricted_or_operator_supplied -eq $true) { $missingRestricted += $entry }
        else { $missingOtherAssets += $entry }
    }
    foreach ($repository in @($strictPreflight.repositories)) {
        if ($repository.present -eq $true -and $repository.clean -eq $true -and $repository.commit_match -eq $true) { continue }
        $repoIssues += [ordered]@{
            name = [string]$repository.name
            relative_path = [string]$repository.relative_path
            present = [bool]$repository.present
            clean = [bool]$repository.clean
            commit_match = [bool]$repository.commit_match
            observed_commit = $repository.observed_commit
            expected_commit = $repository.expected_commit
        }
    }
}

$ready = (
    $uniqueBlockers.Count -eq 0 -and
    $publicReceiptReady -and
    $runtimePythonReady -and
    $runtimeReceiptReady -and
    $materializerPythonReady -and
    $nvccVersion -eq "12.4" -and
    $nvidia.lines.Count -ge 1 -and
    $null -ne $strictPreflight -and
    $strictPreflight.benchmark_environment_ready -eq $true
)

$result = [ordered]@{
    format = "bodyrig-photoreal-exavatar-readiness-doctor"
    version = 1
    bodyrig_revision = $head
    checked_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    distribution = $Distribution
    asset_root = $AssetRoot
    reference_model_root = $ReferenceModelRoot
    smplx_gender = $SmplxGender
    camera_mode = $CameraMode
    linux_dependency_root = $LinuxDependencyRoot
    linux_runtime_python = $LinuxRuntimePython
    linux_materializer_python = $LinuxMaterializerPython
    wsl_ready = $wslReady
    gpus = @($nvidia.lines)
    nvcc_ready = $nvccReady
    nvcc_version = $nvccVersion
    public_dependency_receipt = $publicReceipt
    public_dependency_receipt_ready = $publicReceiptReady
    runtime_receipt = $runtimeReceipt
    runtime_receipt_ready = $runtimeReceiptReady
    runtime_python_ready = $runtimePythonReady
    materializer_python_ready = $materializerPythonReady
    strict_preflight_exit_code = $strictPreflightExit
    strict_preflight_sha256 = $(if ($null -ne $strictPreflight) { $strictPreflight.preflight_sha256 } else { $null })
    missing_restricted_assets = @($missingRestricted)
    missing_nonrestricted_assets = @($missingOtherAssets)
    public_repository_issues = @($repoIssues)
    blockers = @($uniqueBlockers)
    exavatar_launch_prerequisites_ready = [bool]$ready
    mutates_environment = $false
    downloads_assets = $false
    photoreal_acceptance_authority = $false
    human_visual_acceptance_required = $true
    production_activation = $false
}
if (-not [string]::IsNullOrWhiteSpace([string]$preflightError)) {
    $result.strict_preflight_error = $preflightError
}
$result | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $Out -Encoding UTF8

Write-Host "============================================================"
Write-Host "BODYRIG EXAVATAR READINESS DOCTOR"
Write-Host "Revision:          $head"
Write-Host "WSL:               $(if ($wslReady) { 'READY' } else { 'BLOCKED' })"
Write-Host "GPU(s):            $($nvidia.lines.Count)"
foreach ($gpu in @($nvidia.lines)) { Write-Host ("  {0}" -f $gpu) }
Write-Host "NVCC:              $(if ($nvccReady) { $nvccVersion } else { 'MISSING' })"
Write-Host "Public deps:       $(if ($publicReceiptReady) { 'RECEIPT PRESENT' } else { 'MISSING' })"
Write-Host "ExAvatar runtime:  $(if ($runtimePythonReady -and $runtimeReceiptReady) { 'RECEIPT PRESENT' } else { 'MISSING/INCOMPLETE' })"
Write-Host "Restricted miss:   $($missingRestricted.Count)"
Write-Host "Other asset miss:  $($missingOtherAssets.Count)"
Write-Host "Repo issues:       $($repoIssues.Count)"
Write-Host "READY:             $($ready.ToString().ToUpperInvariant())"
Write-Host "Report:            $Out"
Write-Host "Mutations:         NONE"
Write-Host "Production:        FALSE"
Write-Host "============================================================"

if (-not $ready) {
    foreach ($blocker in $uniqueBlockers) { Write-Host ("  blocker: {0}" -f $blocker) }
    exit 2
}
exit 0
