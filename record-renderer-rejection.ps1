param(
    [Parameter(Mandatory = $true)][string]$AcceptanceDir,
    [Parameter(Mandatory = $true)][ValidateSet("windows-unity-univrm", "android-quest-class")][string]$Platform,
    [Parameter(Mandatory = $true)][ValidateSet(
        "source_identity",
        "geometry_proportions",
        "skin_appearance",
        "hair_appearance",
        "eye_appearance",
        "face_secondary",
        "small_anatomical_detail",
        "upper_body_deformation",
        "lower_body_deformation",
        "cross_limb_leakage"
    )][string[]]$FailedCheck,
    [Parameter(Mandatory = $true)][switch]$ConfirmRejection,
    [Parameter(Mandatory = $true)][ValidateLength(1, 4000)][string]$QualityNote
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig renderer human rejection path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig renderer human rejection path."
}
if (-not $ConfirmRejection) {
    throw "Renderer human rejection requires explicit -ConfirmRejection after the physical visual review failed."
}
if ([string]::IsNullOrWhiteSpace($QualityNote)) {
    throw "QualityNote must describe the observed visual fidelity failure."
}
$QualityNote = $QualityNote.Trim()
if ($QualityNote -match '^<[^>]+>$') {
    throw "QualityNote is still a generated placeholder. Record the actual observed rejection reason."
}
if ($null -eq $FailedCheck -or $FailedCheck.Count -lt 1) {
    throw "At least one explicit -FailedCheck is required."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$AcceptanceDir = [System.IO.Path]::GetFullPath($AcceptanceDir)
if (-not (Test-Path -LiteralPath $AcceptanceDir -PathType Container)) {
    throw "Acceptance directory not found: $AcceptanceDir"
}

function Assert-CheckoutAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$ExpectedHead = ""
    )
    $headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve current BodyRig Git revision." }
    $head = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "Current BodyRig Git revision is not canonical." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) {
        throw "BodyRig checkout revision changed while renderer rejection was being written; expected $ExpectedHead, got $head."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not verify BodyRig checkout cleanliness." }
    if ($dirty.Count -gt 0) { throw "BodyRig checkout changed while renderer rejection was being written; checkout is dirty." }
    return $head
}

$initialHead = Assert-CheckoutAuthority -RepoRoot $repoRoot
$pythonCandidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $pythonCandidate -PathType Leaf) {
    $pythonExe = (Resolve-Path -LiteralPath $pythonCandidate).Path
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "BodyRig Python was not found. Activate the validated BodyRig environment or create .venv first."
    }
    $pythonExe = $pythonCommand.Source
}

$previousPythonPath = $env:PYTHONPATH
$rejectionPath = ""
try {
    $env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $repoRoot } else { "$repoRoot;$previousPythonPath" }
    $expectedModule = (Resolve-Path (Join-Path $repoRoot "bodyrig\__init__.py")).Path
    $moduleLines = @(& $pythonExe -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
    if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) {
        throw "BodyRig Python could not prove imported module authority."
    }
    $actualModule = [System.IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
    if (-not [string]::Equals($actualModule, $expectedModule, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BodyRig Python imports bodyrig from a different checkout/package: $actualModule"
    }

    $cliArgs = @(
        "--acceptance-dir", $AcceptanceDir,
        "--platform", $Platform,
        "--quality-note", $QualityNote
    )
    foreach ($check in $FailedCheck) {
        $cliArgs += @("--failed-check", [string]$check)
    }

    Push-Location $repoRoot
    try {
        $output = @(& $pythonExe -m bodyrig.renderer_human_rejection_cli @cliArgs)
        if ($LASTEXITCODE -ne 0) {
            throw "Renderer human rejection CLI failed with exit code $LASTEXITCODE. $($output -join ' ')"
        }
    } finally {
        Pop-Location
    }
    $jsonText = ($output -join "`n").Trim()
    try { $result = $jsonText | ConvertFrom-Json }
    catch { throw "Renderer human rejection CLI did not return canonical JSON." }
    if ($result.ok -ne $true) { throw "Renderer human rejection CLI did not report success." }
    if ($result.human_review_pass -ne $false -or $result.production_activation -ne $false) {
        throw "Renderer rejection receipt must remain non-passing and non-activating."
    }
    $rejectionPath = [string]$result.rejection_path
    if ([string]::IsNullOrWhiteSpace($rejectionPath) -or -not (Test-Path -LiteralPath $rejectionPath -PathType Leaf)) {
        throw "Renderer rejection receipt was not persisted at the returned path."
    }

    try {
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $initialHead)
    } catch {
        if (-not [string]::IsNullOrWhiteSpace($rejectionPath) -and (Test-Path -LiteralPath $rejectionPath -PathType Leaf)) {
            Remove-Item -LiteralPath $rejectionPath -Force
        }
        throw "BodyRig checkout authority changed after renderer rejection write; removed non-authoritative receipt '$rejectionPath'. $($_.Exception.Message)"
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

Write-Host "BodyRig renderer human rejection: RECORDED | $Platform"
Write-Host "Failed checks: $($FailedCheck -join ', ')"
Write-Host "Receipt: $rejectionPath"
Write-Host "Authority: exact Gate A + package/runtime + machine/deformation hashes | production_activation=false"
exit 0
