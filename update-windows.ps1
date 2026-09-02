param(
    [string]$Remote = "origin",
    [string]$Branch = "agent/person-studio-photoreal-20260902",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

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
    $listenerPids = Get-BodyRigListeners
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
        if ((Get-BodyRigListeners).Count -eq 0) { return }
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

Stop-VerifiedBodyRigService

$statePath = Join-Path $env:LOCALAPPDATA "BodyRig\ui-service.json"
Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue

$remoteRef = "refs/remotes/$Remote/$Branch"
$sourceRef = "refs/heads/$Branch"
& git fetch $Remote "$sourceRef`:$remoteRef"
if ($LASTEXITCODE -ne 0) {
    throw "Kunne ikke hente $Remote/$Branch."
}

$target = (& git rev-parse "$Remote/$Branch^{commit}").Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $target -notmatch '^[0-9a-f]{40}$') {
    throw "Kunne ikke resolve exact target revision for $Remote/$Branch."
}

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

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repoets .venv mangler. Opret den først med Python 3.11."
}

& $python -m pip install --disable-pip-version-check -e ".[test]"
if ($LASTEXITCODE -ne 0) {
    throw "BodyRig venv-opdatering fejlede."
}

$start = Join-Path $PSScriptRoot "start-windows.ps1"
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
Write-Host "Branch: $Remote/$Branch"
