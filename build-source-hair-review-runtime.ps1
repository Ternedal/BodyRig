param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$CandidateDir,
    [Parameter(Mandatory = $true)][string]$CandidateWorkspace,
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
function Need-Directory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Invoke-WslRaw {
    param([Parameter(Mandatory = $true)][object[]]$Arguments)
    $lines = @(& $WslExe -d $Distribution -- @Arguments 2>&1)
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Lines = $lines
        Text = ($lines -join "`n").Trim()
    }
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
function Resolve-BodyRigPython {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)
    $local = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $local -PathType Leaf) { return (Resolve-Path -LiteralPath $local).Path }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw "BodyRig Python was not found." }
    return $command.Source
}
function Invoke-BodyRigPython {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $prior = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $(if ([string]::IsNullOrWhiteSpace($prior)) { $RepoRoot } else { "$RepoRoot$([IO.Path]::PathSeparator)$prior" })
        $lines = @(& $Python @Arguments 2>&1)
        $code = $LASTEXITCODE
        foreach ($line in $lines) { Write-Host ([string]$line) }
        if ($code -ne 0) { throw "$Label failed with exit code $code." }
    } finally {
        $env:PYTHONPATH = $prior
    }
}
function Assert-CheckoutAuthority {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headRaw = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is invalid." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) { throw "Source hair review runtime requires an exact clean BodyRig checkout." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig HEAD changed during source hair review runtime build."
    }
    return $head
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig source hair review runtime is Windows/WSL-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7+ is required." }

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$PackagePath = Need-File -Path $PackagePath -Label "Candidate body package"
$CandidateDir = Need-Directory -Path $CandidateDir -Label "Source hair candidate directory"
$CandidateWorkspace = Need-Directory -Path $CandidateWorkspace -Label "Anatomy candidate workspace"
$bridgeScript = Need-File -Path (Join-Path $repoRoot "bodyrig\bridges\sith_hair_review_runtime.py") -Label "Source hair review bridge"
$bridgeScriptSha = Sha256 $bridgeScript

$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Source hair review output already exists: $OutputDir" }
$outputParent = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParent)) { throw "Source hair review output must have a parent directory." }
New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
$partial = Join-Path $outputParent ("." + [IO.Path]::GetFileName($OutputDir) + ".partial-" + [Guid]::NewGuid().ToString("N"))
if (Test-Path -LiteralPath $partial) { throw "Unexpected source hair review staging collision: $partial" }
New-Item -ItemType Directory -Path $partial | Out-Null
$committed = $false

try {
    $python = Resolve-BodyRigPython -RepoRoot $repoRoot
    $versionText = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not query BodyRig Python version." }
    try { $version = [version]$versionText } catch { throw "BodyRig Python returned invalid version: $versionText" }
    if ($version -lt [version]"3.11") { throw "BodyRig Python 3.11+ is required; found $versionText." }

    Invoke-BodyRigPython -Python $python -RepoRoot $repoRoot -Label "Prepare source hair review runtime" -Arguments @(
        "-m", "bodyrig.source_hair_review_runtime", "prepare",
        "--package", $PackagePath,
        "--candidate-dir", $CandidateDir,
        "--output-dir", $partial
    )

    $bindingPath = Need-File -Path (Join-Path $partial "source-hair-body-binding.json") -Label "Prepared source hair/body binding"
    $avatarPath = Need-File -Path (Join-Path $partial "base-avatar.vrm") -Label "Prepared base avatar"
    try { $binding = Get-Content -LiteralPath $bindingPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
    catch { throw "Prepared source hair/body binding is unreadable." }
    if ([string]$binding.format -ne "bodyrig-source-hair-body-binding" -or [int]$binding.version -ne 1 -or
        [string]$binding.avatarVrmSha256 -ne (Sha256 $avatarPath) -or
        $binding.runtimeIntegrationRequired -ne $true -or
        $binding.physicalSilhouetteReviewRequired -ne $true -or
        $binding.comparisonOnly -ne $true -or $binding.humanReviewRequired -ne $true -or
        $binding.productionActivation -ne $false) {
        throw "Prepared source hair/body binding violates review-only authority."
    }

    $wslCommand = Get-Command $WslExe -ErrorAction SilentlyContinue
    if ($null -eq $wslCommand) { throw "WSL executable not found: $WslExe" }
    $WslExe = $wslCommand.Source
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
    foreach ($path in @(
        $venvPython,
        "$modelDir/SMPLX_NEUTRAL.npz", "$modelDir/SMPLX_MALE.npz", "$modelDir/SMPLX_FEMALE.npz"
    )) {
        $probe = Invoke-WslRaw -Arguments @("/usr/bin/test", $(if ($path -eq $venvPython) { "-x" } else { "-f" }), $path)
        if ($probe.ExitCode -ne 0) { throw "Required SiTH/SMPL-X runtime artifact missing: $path" }
    }
    $cudaProbe = Invoke-WslRaw -Arguments @(
        $venvPython, "-c", "import torch,smplx,numpy; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"
    )
    if ($cudaProbe.ExitCode -ne 0) { throw "SiTH hair review CUDA/runtime probe failed: $($cudaProbe.Text)" }

    $avatarWsl = Convert-WindowsPathToWsl -Path $avatarPath
    $bindingWsl = Convert-WindowsPathToWsl -Path $bindingPath
    $workspaceWsl = Convert-WindowsPathToWsl -Path $CandidateWorkspace
    $candidateWsl = Convert-WindowsPathToWsl -Path $CandidateDir
    $bridgeWsl = Convert-WindowsPathToWsl -Path $bridgeScript
    $reviewVrmPath = Join-Path $partial "source-hair-review.vrm"
    $bridgeResultPath = Join-Path $partial "source-hair-review-bridge.json"
    $reviewVrmWsl = Convert-WindowsPathToWsl -Path $reviewVrmPath
    $bridgeResultWsl = Convert-WindowsPathToWsl -Path $bridgeResultPath

    Write-Host "BodyRig source hair review runtime"
    Write-Host "Revision:       $head"
    Write-Host "Package SHA:    $(Sha256 $PackagePath)"
    Write-Host "Binding SHA:    $(Sha256 $bindingPath)"
    Write-Host "Bridge SHA:     $bridgeScriptSha"
    Write-Host "SMPL-X models:  $modelDir"
    Write-Host "Comparison:     TRUE"
    Write-Host "Hair authority: FALSE"
    Write-Host "Production:     FALSE"
    Write-Host ""

    $run = Invoke-WslRaw -Arguments @(
        $venvPython, $bridgeWsl,
        "--avatar-vrm", $avatarWsl,
        "--binding-json", $bindingWsl,
        "--candidate-workspace", $workspaceWsl,
        "--candidate-dir", $candidateWsl,
        "--smplx-model-dir", $modelDir,
        "--output-vrm", $reviewVrmWsl,
        "--output-result", $bridgeResultWsl
    )
    foreach ($line in $run.Lines) { Write-Host ([string]$line) }
    if ($run.ExitCode -ne 0) { throw "Source hair review bridge failed with exit code $($run.ExitCode)." }

    Need-File -Path $reviewVrmPath -Label "Source hair review VRM" | Out-Null
    Need-File -Path $bridgeResultPath -Label "Source hair review bridge result" | Out-Null

    Invoke-BodyRigPython -Python $python -RepoRoot $repoRoot -Label "Finalize source hair review runtime" -Arguments @(
        "-m", "bodyrig.source_hair_review_runtime", "finalize",
        "--package", $PackagePath,
        "--candidate-dir", $CandidateDir,
        "--staging-dir", $partial,
        "--bodyrig-revision", $head,
        "--bridge-script-sha256", $bridgeScriptSha
    )

    $receiptPath = Need-File -Path (Join-Path $partial "source-hair-review-runtime.json") -Label "Source hair review runtime receipt"
    try { $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 30 }
    catch { throw "Source hair review runtime receipt is unreadable." }
    if ([string]$receipt.format -ne "bodyrig-source-hair-review-runtime" -or [int]$receipt.version -ne 1 -or
        [string]$receipt.bodyrigRevision -ne $head -or
        [string]$receipt.bridgeScriptSha256 -ne $bridgeScriptSha -or
        [string]$receipt.reviewVrmSha256 -ne (Sha256 $reviewVrmPath) -or
        [string]$receipt.runtimeIntegrationStatus -ne "review-artifact-ready" -or
        $receipt.physicalSilhouetteReviewRequired -ne $true -or
        $receipt.comparisonOnly -ne $true -or $receipt.humanReviewRequired -ne $true -or
        $receipt.hairComponentAuthority -ne $false -or $receipt.productionActivation -ne $false) {
        throw "Source hair review runtime receipt violates the review-only authority boundary."
    }

    Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head | Out-Null
    if ((Sha256 $bridgeScript) -ne $bridgeScriptSha) {
        throw "Source hair review bridge bytes changed during runtime build."
    }
    if (Test-Path -LiteralPath $OutputDir) { throw "Source hair review output appeared during build: $OutputDir" }
    Move-Item -LiteralPath $partial -Destination $OutputDir
    $committed = $true

    Write-Host ""
    Write-Host "BodyRig source hair review runtime: REVIEW ARTIFACT READY"
    Write-Host "Output:          $OutputDir"
    Write-Host "Review VRM:      $(Join-Path $OutputDir 'source-hair-review.vrm')"
    Write-Host "Human review:    REQUIRED"
    Write-Host "Silhouette gate: REQUIRED"
    Write-Host "Hair authority:  FALSE"
    Write-Host "Production:      FALSE"
    exit 0
} finally {
    if (-not $committed -and (Test-Path -LiteralPath $partial)) {
        Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue
    }
}
