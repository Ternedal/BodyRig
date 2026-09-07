param(
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [ValidatePattern('^$|^[0-9a-fA-F]{40}$')]
    [string]$Revision = "",
    [string]$RepoRoot = "",
    [switch]$NoBrowser,
    [ValidatePattern('^$|^job-[0-9a-f]{32}$')]
    [string]$PreferredJobId = "",
    [ValidatePattern('^$|^person-[0-9a-f]{32}$')]
    [string]$PersonId = "",
    [string]$PerformerId = "",
    [ValidatePattern('^$|^[a-z0-9æøå_-]{1,160}$')]
    [string]$BodyId = "",
    [switch]$SkipPlan
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = $PSScriptRoot
}
$RepoRoot = [System.IO.Path]::GetFullPath($RepoRoot)
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".git") -PathType Container)) {
    throw "RepoRoot er ikke et BodyRig Git-checkout: $RepoRoot"
}
Set-Location $RepoRoot

$hasPerformer = -not [string]::IsNullOrWhiteSpace($PerformerId)
$hasBodyId = -not [string]::IsNullOrWhiteSpace($BodyId)
if ($hasPerformer -xor $hasBodyId) {
    throw "Pass -PerformerId and -BodyId together, or omit both."
}

function Get-BodyRigHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8775/api/v1/health" -TimeoutSec 1
    } catch {
        return $null
    }
}

function Get-BodyRigListeners {
    return @(
        Get-NetTCPConnection -LocalPort 8775 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
}

function Stop-VerifiedBodyRigService {
    $listenerPids = @(Get-BodyRigListeners)
    if ($listenerPids.Count -eq 0) { return }

    $health = Get-BodyRigHealth
    if (-not $health -or $health.ok -ne $true -or [string]$health.service -ne "bodyrig") {
        throw "Port 8775 er optaget, men servicen kan ikke verificeres som BodyRig. Refuserer at stoppe en ukendt proces."
    }

    foreach ($ownerProcessId in $listenerPids) {
        if ([int]$ownerProcessId -le 0) { continue }
        Stop-Process -Id ([int]$ownerProcessId) -Force -ErrorAction Stop
    }

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        $remainingListenerPids = @(Get-BodyRigListeners)
        if ($remainingListenerPids.Count -eq 0) { return }
    }
    throw "BodyRig-servicen slap ikke port 8775 efter stop."
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git mangler."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA er ikke tilgængelig."
}

$dirtyBefore = @(& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke læse Git-status." }
if ($dirtyBefore.Count -gt 0) {
    $dirtyBefore | ForEach-Object { Write-Host $_ }
    throw "BodyRig-checkoutet har lokale ændringer; update refuseres."
}

$original = (& git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $original -notmatch '^[0-9a-f]{40}$') {
    throw "Kunne ikke resolve nuværende BodyRig revision."
}

$remoteRef = "refs/remotes/$Remote/$Branch"
$sourceRef = "refs/heads/$Branch"
& git fetch $Remote "$sourceRef`:$remoteRef"
if ($LASTEXITCODE -ne 0) {
    throw "Kunne ikke hente $Remote/$Branch."
}

$branchTarget = (& git rev-parse "$Remote/$Branch^{commit}").Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $branchTarget -notmatch '^[0-9a-f]{40}$') {
    throw "Kunne ikke resolve exact target revision for $Remote/$Branch."
}

$target = $branchTarget
$targetMode = "branch"
if (-not [string]::IsNullOrWhiteSpace($Revision)) {
    $requested = $Revision.Trim().ToLowerInvariant()
    & git cat-file -e "$requested^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        & git fetch --no-tags $Remote $requested
        if ($LASTEXITCODE -ne 0) {
            throw "Kunne ikke hente requested exact revision $requested fra $Remote."
        }
        & git cat-file -e "$requested^{commit}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "Requested exact revision findes ikke som Git commit: $requested"
        }
    }

    & git merge-base --is-ancestor $requested $branchTarget
    if ($LASTEXITCODE -ne 0) {
        throw "Requested exact revision $requested er ikke en ancestor til fetched $Remote/$Branch $branchTarget. Refuserer historisk evidence-checkout."
    }
    $target = $requested
    $targetMode = "historical-revision"
}

# Fail closed before stopping the currently healthy service. Historical evidence
# checkout is only useful if that exact revision carries the operator/runtime
# files required to reinstall and launch itself authoritatively.
$requiredTargetFiles = @(
    "pyproject.toml",
    "requirements/windows-python.lock.txt",
    "bodyrig/runtime_lock.py",
    "start-windows.ps1",
    "physical-acceptance-status.ps1"
)
foreach ($relativePath in $requiredTargetFiles) {
    & git cat-file -e "$target`:$relativePath" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Target revision $target mangler required operator/runtime file: $relativePath"
    }
}

Stop-VerifiedBodyRigService

$statePath = Join-Path $env:LOCALAPPDATA "BodyRig\ui-service.json"
Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue

& git checkout --detach $target
if ($LASTEXITCODE -ne 0) {
    throw "Kunne ikke checkout exact target revision $target."
}

$actual = (& git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $actual -ne $target) {
    throw "Checkout mismatch: expected $target, got $actual."
}
$dirtyAfter = @(& git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $dirtyAfter.Count -gt 0) {
    throw "Target checkout er ikke clean efter update."
}

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repoets .venv mangler. Opret den først med Python 3.11."
}
$runtimeLock = Join-Path $RepoRoot "requirements\windows-python.lock.txt"
if (-not (Test-Path -LiteralPath $runtimeLock -PathType Leaf)) {
    throw "BodyRig Windows Python runtime lock mangler: $runtimeLock"
}

# The editable BodyRig source lives in this checkout, so a source-only Git update
# does not require reinstalling the package. Skip pip only when both dependency
# authority and the installed editable/launcher authority prove exact. Historical
# revisions that predate install_authority.py deliberately keep the conservative
# reinstall path and then rely on their own start-windows import verification.
$installAuthorityModule = Join-Path $RepoRoot "bodyrig\install_authority.py"
$canVerifyEditableInstall = Test-Path -LiteralPath $installAuthorityModule -PathType Leaf
$runtimeAlreadyValid = $false
if ($canVerifyEditableInstall) {
    $runtimeProbe = @(& $python -m bodyrig.runtime_lock --lock $runtimeLock 2>&1)
    $runtimeProbeExit = $LASTEXITCODE
    $installProbe = @(& $python -m bodyrig.install_authority --repo-root $RepoRoot 2>&1)
    $installProbeExit = $LASTEXITCODE
    if ($runtimeProbeExit -eq 0 -and $installProbeExit -eq 0) {
        $runtimeAlreadyValid = $true
    }
}

if ($runtimeAlreadyValid) {
    Write-Host "BodyRig venv: exact runtime lock + checkout-bound editable install already valid; pip install skipped."
} else {
    if ($canVerifyEditableInstall) {
        Write-Host "BodyRig venv: install/lock authority requires refresh; running canonical pip install."
    } else {
        Write-Host "BodyRig venv: target revision predates editable-install authority probe; using conservative canonical pip install."
    }
    & $python -m pip install --disable-pip-version-check -c $runtimeLock -e ".[test]"
    if ($LASTEXITCODE -ne 0) {
        throw "BodyRig venv-opdatering fejlede."
    }
}

& $python -m bodyrig.runtime_lock --lock $runtimeLock | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig venv matcher ikke den canonical Windows Python runtime lock."
}
if ($canVerifyEditableInstall) {
    & $python -m bodyrig.install_authority --repo-root $RepoRoot | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BodyRig editable install/launcher er ikke authority-bundet til det aktive checkout efter update."
    }
}

$stashPathConfig = Join-Path $RepoRoot "configure-stash-path-map.ps1"
if (Test-Path -LiteralPath $stashPathConfig -PathType Leaf) {
    try {
        & $stashPathConfig
    } catch {
        Remove-Item Env:BODYRIG_STASH_PATH_MAP -ErrorAction SilentlyContinue
        Write-Warning "BodyRig Stash path-map auto-configuration failed: $($_.Exception.Message) Update continues so existing physical evidence can still be inspected/reused; fresh source work remains fail-closed in canonical preflight."
    }
}

$rescueProbe = Join-Path $RepoRoot "diagnose-failed-body-build.ps1"
if (Test-Path -LiteralPath $rescueProbe -PathType Leaf) {
    Write-Host ""
    Write-Host "BodyRig recovery rescue: probing seneste fejlede body-build (read-only)"
    try {
        & $rescueProbe -RepoRoot $RepoRoot
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Recovery rescue probe returnerede exit code $LASTEXITCODE; update fortsætter."
        }
    } catch {
        Write-Warning "Recovery rescue probe kunne ikke gennemføres: $($_.Exception.Message). Update fortsætter."
    }
    Write-Host ""
}

$start = Join-Path $RepoRoot "start-windows.ps1"
if ($NoBrowser) {
    & $start -NoBrowser
} else {
    & $start
}
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig start fejlede efter update."
}

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    throw "BodyRig startede uden verificerbar launcher-state."
}
$state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$state.revision -ne $target) {
    throw "Forkert BodyRig-revision kører efter update: $($state.revision); expected $target."
}
$health = Get-BodyRigHealth
if (-not $health -or $health.ok -ne $true -or [string]$health.service -ne "bodyrig") {
    throw "BodyRig health kunne ikke verificeres efter update."
}

Write-Host "BodyRig update: READY"
Write-Host "Revision: $target"
Write-Host "Authority mode: $targetMode"
Write-Host "Branch authority: $Remote/$Branch @ $branchTarget"
if ($targetMode -eq "historical-revision") {
    Write-Host "Historical evidence continuation is pinned to exact ancestor revision $target."
    Write-Host "Return to current main only after this evidence chain is deliberately completed or abandoned."
    Write-Host "Auto-planning is skipped in historical-revision mode; continue with the revision-bound physical-acceptance-status command that selected this checkout."
} elseif ($SkipPlan) {
    Write-Host "Rig-window auto-plan: skipped by -SkipPlan."
} else {
    $planner = Join-Path $RepoRoot "plan-rig-window.ps1"
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $planner -PathType Leaf)) {
        Write-Warning "BodyRig update er READY, men rig-window planner mangler: $planner"
    } elseif ($null -eq $pwsh) {
        Write-Warning "BodyRig update er READY, men pwsh (PowerShell 7+) mangler; rig-window auto-plan kunne ikke køres."
    } else {
        Write-Host ""
        Write-Host "BodyRig rig-window auto-plan (read-only)"
        $plannerArgs = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $planner
        )
        if (-not [string]::IsNullOrWhiteSpace($PreferredJobId)) {
            $plannerArgs += @("-PreferredJobId", $PreferredJobId)
        }
        if (-not [string]::IsNullOrWhiteSpace($PersonId)) {
            $plannerArgs += @("-PersonId", $PersonId)
        }
        if ($hasPerformer) {
            $plannerArgs += @("-PerformerId", $PerformerId, "-BodyId", $BodyId)
        }
        & $pwsh.Source @plannerArgs
        $plannerExit = $LASTEXITCODE
        if ($plannerExit -ne 0) {
            Write-Warning "BodyRig update er READY, men rig-window auto-plan kunne ikke resolve en sikker næste handling (exit $plannerExit). Kør plan-rig-window.ps1 igen med eksplicit -PersonId/-PerformerId/-BodyId hvis scope er tvetydigt."
        }
    }
}
