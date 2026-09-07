param(
    [Parameter(Mandatory = $true)][string]$SessionReport,
    [string]$BodyRigPython = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "The canonical BodyRig physical acceptance path is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for the canonical BodyRig physical acceptance path."
}
$pwshAuthority = Get-Command pwsh -ErrorAction SilentlyContinue
if ($null -eq $pwshAuthority) {
    throw "PowerShell 7 executable (pwsh) was not found for the canonical BodyRig physical acceptance path."
}

function Resolve-InputFile {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Resolve-InputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path,[Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "$Label not found: $Path" }
    return (Resolve-Path -LiteralPath $Path).Path
}
function Assert-CheckoutAuthority {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$ExpectedHead = ""
    )
    $headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) {
        throw "Could not bind transactional Gate A to BodyRig Git HEAD."
    }
    $currentHead = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($currentHead -notmatch '^[0-9a-f]{40}$') {
        throw "BodyRig Git HEAD is not canonical for transactional Gate A."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $currentHead -ne $ExpectedHead) {
        throw "BodyRig checkout revision changed during transactional Gate A; expected $ExpectedHead, got $currentHead."
    }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
    if ($dirty.Count -gt 0) {
        throw "BodyRig checkout is dirty; transactional Gate A requires an exact clean checkout."
    }
    return $currentHead
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CheckoutAuthority -RepoRoot $repoRoot
$coreScript = Resolve-InputFile -Path (Join-Path $repoRoot "accept-physical-clone-core.ps1") -Label "Gate A transactional core"
$SessionReport = Resolve-InputFile -Path $SessionReport -Label "Physical clone session report"

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Resolve-InputFile -Path $BodyRigPython -Label "BodyRig Python"
$expectedBodyRigModule = Resolve-InputFile -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "BodyRig checkout Python module"
$moduleAuthorityLines = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleAuthorityLines.Count -ne 1) {
    throw "BodyRig Python could not prove its imported bodyrig module authority before transactional Gate A."
}
$actualBodyRigModule = [System.IO.Path]::GetFullPath(([string]$moduleAuthorityLines[0]).Trim())
if (-not [string]::Equals($actualBodyRigModule, $expectedBodyRigModule, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BodyRig Python imports bodyrig from a different checkout/package: $actualBodyRigModule"
}

$sessionRaw = @(& $BodyRigPython -m bodyrig.physical_session validate $SessionReport)
if ($LASTEXITCODE -ne 0 -or $sessionRaw.Count -ne 1) {
    throw "Physical clone session failed strict validation before transactional Gate A."
}
try { $session = ([string]$sessionRaw[0]) | ConvertFrom-Json }
catch { throw "Physical clone session validator returned unreadable JSON before transactional Gate A." }
if ([string]$session.status -ne "pass" -or [string]$session.stage -ne "complete") {
    throw "Physical clone session is not a completed PASS."
}
if ($session.bodyrig_checkout_clean -ne $true) {
    throw "Physical clone session did not start from a clean BodyRig checkout."
}
if (([string]$session.bodyrig_revision).ToLowerInvariant() -ne $head) {
    throw "Current BodyRig HEAD does not match the physical clone session revision."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $cloneRoot = Resolve-InputDirectory -Path ([string]$session.clone_output) -Label "Physical clone output"
    $OutputDir = Join-Path $cloneRoot "acceptance"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) {
    throw "Acceptance output already exists; refusing cross-run reuse: $OutputDir"
}
$outputParentText = Split-Path -Parent $OutputDir
if ([string]::IsNullOrWhiteSpace($outputParentText)) { throw "Acceptance output must have an existing parent directory." }
$outputParent = Resolve-InputDirectory -Path $outputParentText -Label "Acceptance output parent"
$outputLeaf = Split-Path -Leaf $OutputDir
if ([string]::IsNullOrWhiteSpace($outputLeaf)) { throw "Acceptance output must have a directory name." }
$staging = Join-Path $outputParent ("." + $outputLeaf + ".gate-a-" + [Guid]::NewGuid().ToString("N") + ".tmp")
$published = $false

try {
    $coreArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $coreScript,
        "-SessionReport", $SessionReport,
        "-BodyRigPython", $BodyRigPython,
        "-OutputDir", $staging
    )
    $coreOutput = @(& $pwshAuthority.Source @coreArgs 2>&1)
    $coreExit = $LASTEXITCODE
    if ($coreExit -ne 0) {
        foreach ($line in $coreOutput) { Write-Host ([string]$line) }
        throw "Gate A core failed with exit code $coreExit; canonical acceptance was not published."
    }
    if (-not (Test-Path -LiteralPath $staging -PathType Container)) {
        throw "Gate A core reported success without a staging acceptance directory."
    }
    $stagingMarker = Join-Path $staging "bodyrig-acceptance.json"
    if (-not (Test-Path -LiteralPath $stagingMarker -PathType Leaf)) {
        throw "Gate A core reported success without a canonical acceptance marker."
    }

    & $BodyRigPython -m bodyrig.rig_window_acceptance $staging | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Gate A staging bundle failed structural reuse validation; canonical acceptance was not published."
    }
    [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head)
    if (Test-Path -LiteralPath $OutputDir) {
        throw "Canonical acceptance appeared during Gate A staging; refusing to overwrite: $OutputDir"
    }

    [System.IO.Directory]::Move($staging, $OutputDir)
    try {
        $publishedMarker = Join-Path $OutputDir "bodyrig-acceptance.json"
        if (-not (Test-Path -LiteralPath $publishedMarker -PathType Leaf)) {
            throw "Transactional Gate A publication completed without its canonical acceptance marker."
        }
        [void](Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head)
    } catch {
        if (Test-Path -LiteralPath $OutputDir -PathType Container) {
            Remove-Item -LiteralPath $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw
    }
    $published = $true

    Write-Host "BodyRig transactional Gate A publication: PASS"
    Write-Host "Revision: $head"
    Write-Host "Acceptance: $OutputDir"
    Write-Host "Acceptance report: $publishedMarker"
    exit 0
}
finally {
    if (-not $published -and (Test-Path -LiteralPath $staging)) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}
