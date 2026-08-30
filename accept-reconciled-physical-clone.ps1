param(
    [Parameter(Mandatory = $true)][string]$SessionReport,
    [Parameter(Mandatory = $true)][string]$CloneOutput,
    [Parameter(Mandatory = $true)][string]$ExpectedSourceRevision,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedPackageSha256,
    [Parameter(Mandatory = $true)][string[]]$ObservedDirtyPath,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$BodyRigPython = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$expectedFailure = "BodyRig checkout became dirty during the physical clone session; refusing PASS evidence."
$allowedDelta = @(
    ".gitignore",
    "tests/test_repository_hygiene.py",
    "accept-reconciled-physical-clone.ps1",
    "tests/test_reconciled_acceptance_contract.py"
)

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

function Assert-CleanCheckout {
    param([Parameter(Mandatory = $true)][string]$RepoRoot,[string]$ExpectedHead = "")
    $headLines = @(& git -C $RepoRoot rev-parse HEAD 2>&1)
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1) { throw "Could not resolve BodyRig HEAD." }
    $head = ([string]$headLines[0]).Trim().ToLowerInvariant()
    if ($head -notmatch '^[0-9a-f]{40}$') { throw "BodyRig HEAD is not canonical." }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedHead) -and $head -ne $ExpectedHead) { throw "BodyRig HEAD changed during reconciliation; expected $ExpectedHead, got $head." }
    $dirty = @(& git -C $RepoRoot status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect BodyRig Git status." }
    if ($dirty.Count -gt 0) { throw "BodyRig checkout is dirty; reconciliation requires an exact clean checkout." }
    return $head
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Physical clone reconciliation is Windows-only."
}
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required for physical clone reconciliation."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$head = Assert-CleanCheckout -RepoRoot $repoRoot
$ExpectedSourceRevision = $ExpectedSourceRevision.Trim().ToLowerInvariant()
$ExpectedPackageSha256 = $ExpectedPackageSha256.Trim().ToLowerInvariant()
if ($ExpectedSourceRevision -notmatch '^[0-9a-f]{40}$') { throw "ExpectedSourceRevision must be a canonical 40-character Git SHA." }

if ([string]::IsNullOrWhiteSpace($BodyRigPython)) {
    $candidate = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $BodyRigPython = $candidate }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "BodyRig Python not found." }
        $BodyRigPython = $python.Source
    }
}
$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"

$expectedModule = Need-File -Path (Join-Path $repoRoot "bodyrig\__init__.py") -Label "BodyRig checkout module"
$moduleLines = @(& $BodyRigPython -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())" 2>&1)
if ($LASTEXITCODE -ne 0 -or $moduleLines.Count -ne 1) { throw "BodyRig Python could not prove checkout module authority." }
$actualModule = [IO.Path]::GetFullPath(([string]$moduleLines[0]).Trim())
if (-not [string]::Equals($actualModule, $expectedModule, [StringComparison]::OrdinalIgnoreCase)) { throw "BodyRig Python imports bodyrig from unexpected location: $actualModule" }

$SessionReport = Need-File -Path $SessionReport -Label "Original physical clone session"
$readinessPath = [IO.Path]::ChangeExtension($SessionReport, "readiness.json")
$readinessPath = Need-File -Path $readinessPath -Label "Original physical clone readiness"
$CloneOutput = Need-Directory -Path $CloneOutput -Label "Original physical clone output"
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $OutputDir) { throw "Reconciled acceptance output already exists; refusing cross-attempt reuse: $OutputDir" }

$sessionRaw = @(& $BodyRigPython -m bodyrig.physical_session validate $SessionReport)
if ($LASTEXITCODE -ne 0 -or $sessionRaw.Count -ne 1) { throw "Original physical clone session failed strict validation." }
try { $session = ([string]$sessionRaw[0]) | ConvertFrom-Json }
catch { throw "Original physical clone session validator returned unreadable JSON." }

if ([string]$session.status -ne "fail" -or [string]$session.stage -ne "clone") { throw "Reconciliation only accepts a terminal clone-stage FAIL session." }
if ($session.bodyrig_checkout_clean -ne $true) { throw "Original session did not start from a clean checkout." }
if ([string]$session.error -ne $expectedFailure) { throw "Original session failure is not the bytecode-only postflight failure class." }
$sourceRevision = ([string]$session.bodyrig_revision).ToLowerInvariant()
if ($sourceRevision -ne $ExpectedSourceRevision) { throw "Original session revision $sourceRevision does not match ExpectedSourceRevision $ExpectedSourceRevision." }
if ([string]$session.readiness_sha256 -notmatch '^[0-9a-f]{64}$') { throw "Original session readiness hash is invalid." }
if ((Sha256 $readinessPath) -ne ([string]$session.readiness_sha256).ToLowerInvariant()) { throw "Original readiness bytes no longer match the failed session." }

& git -C $repoRoot cat-file -e "$sourceRevision^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) { throw "Original session revision is not present in the local Git object database: $sourceRevision" }
& git -C $repoRoot merge-base --is-ancestor $sourceRevision $head
if ($LASTEXITCODE -ne 0) { throw "Current HEAD is not a descendant of the original physical clone revision." }

$deltaLines = @(& git -C $repoRoot diff --name-status "$sourceRevision..$head")
if ($LASTEXITCODE -ne 0) { throw "Could not inspect revision delta from physical clone to reconciliation HEAD." }
$deltaNames = @()
foreach ($line in $deltaLines) {
    if ([string]::IsNullOrWhiteSpace([string]$line)) { continue }
    $parts = ([string]$line) -split "`t"
    if ($parts.Count -ne 2 -or $parts[0] -notin @("A", "M")) { throw "Unsupported revision delta during reconciliation: $line" }
    $deltaNames += $parts[1]
}
$deltaNames = @($deltaNames | Sort-Object -Unique)
$expectedNames = @($allowedDelta | Sort-Object -Unique)
if (@(Compare-Object -ReferenceObject $expectedNames -DifferenceObject $deltaNames).Count -ne 0) {
    throw "Revision delta is broader than the approved Python-bytecode hygiene/reconciliation fix: $($deltaNames -join ', ')"
}

$gitignore = Need-File -Path (Join-Path $repoRoot ".gitignore") -Label ".gitignore"
$gitignoreLines = @(Get-Content -LiteralPath $gitignore -Encoding UTF8)
if ($gitignoreLines -notcontains "__pycache__/" -or $gitignoreLines -notcontains "*.py[cod]") { throw "Current .gitignore does not contain the canonical Python bytecode exclusions." }
$hygieneTest = Need-File -Path (Join-Path $repoRoot "tests\test_repository_hygiene.py") -Label "Repository hygiene regression"
& $BodyRigPython -m pytest -q $hygieneTest
if ($LASTEXITCODE -ne 0) { throw "Repository hygiene regression did not pass on reconciliation HEAD." }

$normalizedDirty = @()
foreach ($item in $ObservedDirtyPath) {
    $normalized = ([string]$item).Trim().Replace('\', '/')
    if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized -notmatch '(^|/)__pycache__/[^/]+\.pyc$') {
        throw "Observed dirty path is outside the approved Python bytecode failure class: $item"
    }
    $normalizedDirty += $normalized
}
$normalizedDirty = @($normalizedDirty | Sort-Object -Unique)
if ($normalizedDirty.Count -lt 1) { throw "At least one observed Python bytecode path is required." }

$alias = [string]$session.body_id
$cloneDir = Need-Directory -Path (Join-Path $CloneOutput "clone") -Label "Portable clone artifact directory"
$packagePath = Need-File -Path (Join-Path $cloneDir "$alias.mrbody") -Label "Physical clone .mrbody"
$packageHash = Sha256 $packagePath
if ($packageHash -ne $ExpectedPackageSha256) { throw "Physical clone package SHA-256 mismatch; expected $ExpectedPackageSha256, got $packageHash." }
foreach ($requiredName in @("bodyrig-recovery-proof.json", "bodyrig-visual-identity.json", "bodyrig-portable-identity.json", "bodyrig-source-evidence.json")) {
    [void](Need-File -Path (Join-Path $cloneDir $requiredName) -Label $requiredName)
}

$packageCheck = @(& $BodyRigPython -c "import hashlib,json,pathlib,sys; from bodyrig.package import validate_package; p=pathlib.Path(sys.argv[1]).resolve(); v=validate_package(p); print(json.dumps({'body_id':v.manifest['id'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest()},separators=(',',':')))" $packagePath)
if ($LASTEXITCODE -ne 0 -or $packageCheck.Count -ne 1) { throw "Physical clone package failed strict validation before reconciliation." }
try { $packageInfo = ([string]$packageCheck[0]) | ConvertFrom-Json }
catch { throw "Physical clone package validator returned unreadable JSON." }
if ([string]$packageInfo.sha256 -ne $ExpectedPackageSha256) { throw "Strict package validation did not preserve expected SHA-256." }

$sessionHash = Sha256 $SessionReport
$readinessHash = Sha256 $readinessPath
$reconciliation = [ordered]@{
    format = "bodyrig-physical-clone-reconciliation"
    version = 1
    created_at = [DateTime]::UtcNow.ToString("o")
    attestation = "operator-supplied"
    failure_class = "python-bytecode-postflight-false-negative"
    original_session_sha256 = $sessionHash
    original_session_status = "fail"
    original_failure = $expectedFailure
    original_bodyrig_revision = $sourceRevision
    reconciled_bodyrig_revision = $head
    readiness_sha256 = $readinessHash
    requested_alias = $alias
    canonical_body_id = [string]$packageInfo.body_id
    package_sha256 = $packageHash
    observed_dirty_paths = $normalizedDirty
    approved_revision_delta = $expectedNames
    original_session_preserved = $true
    recovery_rerun = $false
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-reconciled-gate-a-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$committed = $false
try {
    $tempSession = Join-Path $tempRoot "reconciled-session.json"
    $tempReadiness = [IO.Path]::ChangeExtension($tempSession, "readiness.json")
    Copy-Item -LiteralPath $readinessPath -Destination $tempReadiness

    # Preserve the original ISO-8601 timestamp strings byte-for-byte through Python JSON.
    # PowerShell 7.5+ may deserialize ISO timestamps as DateTime and a later [string] cast
    # is culture-dependent, which would make the strict physical-session validator reject them.
    $syntheticCode = @'
import json
import pathlib
import sys
source = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
source["status"] = "pass"
source["stage"] = "complete"
source["bodyrig_revision"] = sys.argv[2]
source["bodyrig_checkout_clean"] = True
source["clone_output"] = sys.argv[3]
source["error"] = None
pathlib.Path(sys.argv[4]).write_text(
    json.dumps(source, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
    newline="\n",
)
'@
    & $BodyRigPython -c $syntheticCode $SessionReport $head $CloneOutput $tempSession
    if ($LASTEXITCODE -ne 0) { throw "Could not create ephemeral reconciliation session without timestamp coercion." }
    & $BodyRigPython -m bodyrig.physical_session validate $tempSession | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Ephemeral reconciliation session failed strict schema validation." }

    $gateA = Join-Path $repoRoot "accept-physical-clone.ps1"
    if (-not (Test-Path -LiteralPath $gateA -PathType Leaf)) { throw "Canonical Gate A script not found: $gateA" }
    & $gateA -SessionReport $tempSession -BodyRigPython $BodyRigPython -OutputDir $OutputDir
    if ($LASTEXITCODE -ne 0) { throw "Canonical Gate A failed during reconciled acceptance." }

    $acceptancePath = Need-File -Path (Join-Path $OutputDir "bodyrig-acceptance.json") -Label "Gate A acceptance report"
    $sessionCopy = Need-File -Path (Join-Path $OutputDir "bodyrig-physical-clone-session.json") -Label "Gate A session evidence"
    $readinessCopy = Need-File -Path (Join-Path $OutputDir "bodyrig-rig-readiness.json") -Label "Gate A readiness evidence"
    if ((Sha256 $readinessCopy) -ne $readinessHash) { throw "Gate A readiness copy differs from original physical readiness evidence." }

    Copy-Item -LiteralPath $SessionReport -Destination $sessionCopy -Force
    if ((Sha256 $sessionCopy) -ne $sessionHash) { throw "Original failed session changed while rebinding reconciled Gate A evidence." }

    $reconciliationPath = Join-Path $OutputDir "bodyrig-physical-clone-reconciliation.json"
    $reconciliation | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $reconciliationPath -Encoding UTF8
    $reconciliationHash = Sha256 $reconciliationPath

    try { $acceptance = Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "Gate A acceptance report is not valid JSON after canonical Gate A completion." }
    if ([string]$acceptance.bodyrig_revision -ne $head -or $acceptance.automated_pass -ne $true -or [string]$acceptance.physical_renderer_acceptance -ne "pending") {
        throw "Canonical Gate A output is not a pending automated PASS on the reconciliation HEAD."
    }
    if ([string]$acceptance.package.package_sha256 -ne $ExpectedPackageSha256) { throw "Gate A accepted package hash differs from reconciled package hash." }

    $acceptance.physical_clone.session_sha256 = $sessionHash
    $acceptance.physical_clone | Add-Member -NotePropertyName reconciliation_sha256 -NotePropertyValue $reconciliationHash -Force
    $acceptance.physical_clone | Add-Member -NotePropertyName source_bodyrig_revision -NotePropertyValue $sourceRevision -Force
    $acceptance.physical_clone | Add-Member -NotePropertyName reconciled -NotePropertyValue $true -Force

    $tempAcceptance = Join-Path $OutputDir (".bodyrig-acceptance-rebind-" + [Guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $acceptance | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $tempAcceptance -Encoding UTF8
        Move-Item -LiteralPath $tempAcceptance -Destination $acceptancePath -Force
    } finally {
        if (Test-Path -LiteralPath $tempAcceptance) { Remove-Item -LiteralPath $tempAcceptance -Force }
    }

    $reloaded = Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($reloaded.physical_clone.reconciled -ne $true -or [string]$reloaded.physical_clone.reconciliation_sha256 -ne $reconciliationHash -or [string]$reloaded.physical_clone.session_sha256 -ne $sessionHash) {
        throw "Reconciled Gate A binding failed final self-check."
    }
    if ((Assert-CleanCheckout -RepoRoot $repoRoot -ExpectedHead $head) -ne $head) { throw "Unexpected checkout authority result after reconciliation." }

    $committed = $true
    Write-Host "BodyRig reconciled Gate A: PASS"
    Write-Host "Original physical session preserved as FAIL: $SessionReport"
    Write-Host "Source revision:      $sourceRevision"
    Write-Host "Acceptance revision:  $head"
    Write-Host "Package SHA-256:      $packageHash"
    Write-Host "Reconciliation:       $reconciliationPath"
    Write-Host "Acceptance directory: $OutputDir"
    Write-Host "Recovery rerun:        NO"
} finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
    if (-not $committed -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
        Remove-Item -LiteralPath $OutputDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit 0