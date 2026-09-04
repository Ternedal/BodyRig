param(
    [Parameter(Mandatory = $true)][string]$DonorObj,
    [Parameter(Mandatory = $true)][ValidateSet("female", "male", "neutral")][string]$TargetFamily,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$InstallRoot = "",
    [string]$WslExe = "wsl.exe"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Invoke-WslRaw {
    param([Parameter(Mandatory = $true)][object[]]$Arguments)
    $lines = @(& $WslExe -d $Distribution -- @Arguments 2>&1)
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Lines = $lines; Text = ($lines -join "`n").Trim() }
}
function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $escaped = $Path.Replace('\', '\\')
    $result = Invoke-WslRaw -Arguments @("wslpath", "-a", "-u", $escaped)
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Text)) {
        throw "WSL path translation failed for $Path`: $($result.Text)"
    }
    return $result.Text.Trim()
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig eye component extraction is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
$head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Eye component extraction requires an exact clean BodyRig checkout." }

$DonorObj = Need-File -Path $DonorObj -Label "Subject donor OBJ"
$extractScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_eye_component_extract.py") -Label "BodyRig eye extraction bridge"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Eye component output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Eye component output must have a parent directory." }
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null

$WslExeResolved = Get-Command $WslExe -ErrorAction SilentlyContinue
if ($null -eq $WslExeResolved) { throw "WSL executable not found: $WslExe" }
$WslExe = $WslExeResolved.Source
if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "WSL distribution is required." }
if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $home = Invoke-WslRaw -Arguments @("/usr/bin/python3", "-c", "import pathlib; print(pathlib.Path.home().as_posix())")
    if ($home.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($home.Text)) {
        throw "Could not resolve WSL home directory: $($home.Text)"
    }
    $InstallRoot = "$($home.Text.Trim())/.local/share/bodyrig/sith"
}
if (-not $InstallRoot.StartsWith("/")) { throw "-InstallRoot must be an absolute Linux path." }
$InstallRoot = $InstallRoot.TrimEnd("/")
$venvPython = "$InstallRoot/.bodyrig-venv/bin/python"
$modelDir = "$InstallRoot/data/body_models/smplx"
$pythonProbe = Invoke-WslRaw -Arguments @("/usr/bin/test", "-x", $venvPython)
if ($pythonProbe.ExitCode -ne 0) { throw "SiTH WSL Python not found or not executable: $venvPython" }

$donorWsl = Convert-WindowsPathToWsl -Path $DonorObj
$outputWsl = Convert-WindowsPathToWsl -Path $OutputDir
$scriptWsl = Convert-WindowsPathToWsl -Path $extractScript

Write-Host "BodyRig explicit eye geometry extraction"
Write-Host "Revision:      $head"
Write-Host "Target family: $TargetFamily"
Write-Host "Donor OBJ:     $DonorObj"
Write-Host "Iris source:   MISSING (explicitly not claimed)"
Write-Host "Production:    FALSE"
Write-Host ""

$run = Invoke-WslRaw -Arguments @(
    $venvPython,
    $scriptWsl,
    "--smplx-model-dir", $modelDir,
    "--target-family", $TargetFamily,
    "--donor-obj", $donorWsl,
    "--output-dir", $outputWsl
)
foreach ($line in $run.Lines) { Write-Host ([string]$line) }
if ($run.ExitCode -ne 0) { throw "Eye component extraction failed with exit code $($run.ExitCode)." }

$evidencePath = Need-File -Path (Join-Path $OutputDir "eye-component-candidate.json") -Label "Eye component evidence"
$leftObj = Need-File -Path (Join-Path $OutputDir "left_eye.obj") -Label "Left eye OBJ"
$rightObj = Need-File -Path (Join-Path $OutputDir "right_eye.obj") -Label "Right eye OBJ"
try { $evidence = Get-Content -LiteralPath $evidencePath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 20 }
catch { throw "Eye component evidence is unreadable." }
if ([string]$evidence.format -ne "bodyrig-eye-component-candidate" -or [int]$evidence.version -ne 1 -or
    $evidence.explicitEyeGeometry -ne $true -or $evidence.sourceDerivedIrisAppearance -ne $false -or
    [string]$evidence.componentStatus -ne "partial" -or $evidence.bodyTopologyModified -ne $false -or
    $evidence.generativeIdentitySynthesis -ne $false -or $evidence.humanReviewRequired -ne $true -or
    $evidence.productionReady -ne $false) {
    throw "Eye component evidence violates the high-fidelity authority boundary."
}

Write-Host ""
Write-Host "BodyRig eye component extraction: PARTIAL PASS"
Write-Host "Left eye:       $leftObj"
Write-Host "Right eye:      $rightObj"
Write-Host "Left faces:     $([int]$evidence.leftEyeFaceCount)"
Write-Host "Right faces:    $([int]$evidence.rightEyeFaceCount)"
Write-Host "Iris:           MISSING"
Write-Host "Cornea:         MISSING"
Write-Host "Eyelashes:      MISSING"
Write-Host "Human review:   REQUIRED"
Write-Host "Production:     FALSE"
exit 0
