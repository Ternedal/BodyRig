param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

function Test-SamePath([string]$Left, [string]$Right) {
    if ([string]::IsNullOrWhiteSpace($Left) -or [string]::IsNullOrWhiteSpace($Right)) { return $false }
    try {
        return [string]::Equals(
            [System.IO.Path]::GetFullPath($Left).TrimEnd('\'),
            [System.IO.Path]::GetFullPath($Right).TrimEnd('\'),
            [System.StringComparison]::OrdinalIgnoreCase
        )
    } catch {
        return $false
    }
}

function Get-BodyRigHealth {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:8775/api/v1/health" -TimeoutSec 1
    } catch {
        return $null
    }
}

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Exe = Join-Path $PSScriptRoot ".venv\Scripts\bodyrig.exe"
foreach ($required in @($Python, $Exe)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "BodyRig UI er ikke installeret i repoets .venv. Kør bootstrap fra README: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e '.[test]'"
    }
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git mangler og BodyRig kan ikke bevise checkout-authority."
}

$ExpectedRoot = (Resolve-Path $PSScriptRoot).Path
$ExpectedModule = (Resolve-Path (Join-Path $PSScriptRoot "bodyrig\__init__.py")).Path
$ActualModule = (& $Python -c "import pathlib, bodyrig; print(pathlib.Path(bodyrig.__file__).resolve())").Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-SamePath $ExpectedModule $ActualModule)) {
    throw "Repoets .venv importerer ikke BodyRig fra dette checkout: $ActualModule"
}

$ExpectedHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $ExpectedHead -notmatch '^[0-9a-f]{40}$') {
    throw "Kunne ikke aflæse BodyRig Git HEAD."
}
$Dirty = (& git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke aflæse BodyRig Git-status." }
if ($Dirty) {
    throw "BodyRig-checkoutet har lokale ændringer. Produktstart kræver et clean checkout."
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA er ikke tilgængelig; BodyRig kan ikke gemme sikker UI-process state."
}
$StateDir = Join-Path $env:LOCALAPPDATA "BodyRig"
$ConfigDir = Join-Path $StateDir "config"
$StashConfigPath = Join-Path $ConfigDir "stash.json"
$StatePath = Join-Path $StateDir "ui-service.json"
New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null

function Save-StashLocalConfig {
    if ([string]::IsNullOrWhiteSpace($env:STASH_URL) -or [string]::IsNullOrWhiteSpace($env:STASH_API_KEY)) { return }
    $secure = ConvertTo-SecureString $env:STASH_API_KEY -AsPlainText -Force
    $protected = ConvertFrom-SecureString $secure
    $config = [ordered]@{
        format = "bodyrig-local-stash-config"
        version = 1
        url = $env:STASH_URL.Trim()
        api_key_dpapi = $protected
        updated_utc = [DateTime]::UtcNow.ToString("o")
    }
    $temp = "$StashConfigPath.tmp-$([Guid]::NewGuid().ToString('N'))"
    [System.IO.File]::WriteAllText($temp, (($config | ConvertTo-Json -Depth 4) + "`n"), [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $StashConfigPath -Force
}

function Restore-StashLocalConfig {
    if (-not (Test-Path -LiteralPath $StashConfigPath -PathType Leaf)) { return }
    try {
        $config = Get-Content -LiteralPath $StashConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return
    }
    if ([string]$config.format -ne "bodyrig-local-stash-config" -or [int]$config.version -ne 1) { return }
    $savedUrl = [string]$config.url
    if ([string]::IsNullOrWhiteSpace($savedUrl) -or [string]::IsNullOrWhiteSpace([string]$config.api_key_dpapi)) { return }

    if ([string]::IsNullOrWhiteSpace($env:STASH_URL)) {
        $env:STASH_URL = $savedUrl
    }
    if (-not [string]::Equals($env:STASH_URL.Trim(), $savedUrl.Trim(), [System.StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    if (-not [string]::IsNullOrWhiteSpace($env:STASH_API_KEY)) { return }

    try {
        $secure = ConvertTo-SecureString ([string]$config.api_key_dpapi)
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $env:STASH_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    } catch {
        $env:STASH_API_KEY = $null
    }
}

Restore-StashLocalConfig
Save-StashLocalConfig

function Read-LaunchState {
    if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) { return $null }
    try {
        $state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
    if ([string]$state.format -ne "bodyrig-ui-service" -or [int]$state.version -ne 1) { return $null }
    return $state
}

function Assert-CurrentLaunchState($State, $Health) {
    if (-not $Health -or $Health.ok -ne $true -or [string]$Health.service -ne "bodyrig") {
        throw "Port 8775 svarer, men servicen identificerer sig ikke sikkert som BodyRig."
    }
    if ($null -eq $State) {
        throw "En BodyRig-service kører allerede på port 8775, men den kan ikke bindes til denne checkout-launcher. Stop den anden service før produktstart."
    }
    if (-not (Test-SamePath ([string]$State.root) $ExpectedRoot) -or [string]$State.revision -ne $ExpectedHead) {
        throw "En BodyRig-service kører allerede, men launcher-state tilhører et andet checkout eller en anden revision."
    }
    $pidValue = [int]$State.pid
    if ($pidValue -le 0 -or $null -eq (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
        throw "BodyRig health svarer, men launcherens PID-state er ikke længere gyldig. Stop den eksisterende service og start igen."
    }
}

$Health = Get-BodyRigHealth
if ($Health) {
    Assert-CurrentLaunchState (Read-LaunchState) $Health
} else {
    $old = Read-LaunchState
    if ($old) {
        $oldPid = [int]$old.pid
        if ($oldPid -le 0 -or $null -eq (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
        }
    }

    $Process = Start-Process -FilePath (Resolve-Path $Exe).Path -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    $Ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 250
        $Health = Get-BodyRigHealth
        if ($Health -and $Health.ok -eq $true -and [string]$Health.service -eq "bodyrig") {
            $Ready = $true
            break
        }
        if ($Process.HasExited) { break }
    }
    if (-not $Ready) {
        if (-not $Process.HasExited) { Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue }
        throw "BodyRig UI startede ikke korrekt på 127.0.0.1:8775."
    }

    $state = [ordered]@{
        format = "bodyrig-ui-service"
        version = 1
        pid = $Process.Id
        root = $ExpectedRoot
        revision = $ExpectedHead
        started_utc = [DateTime]::UtcNow.ToString("o")
    }
    $temp = "$StatePath.tmp-$([Guid]::NewGuid().ToString('N'))"
    [System.IO.File]::WriteAllText($temp, (($state | ConvertTo-Json -Depth 4) + "`n"), [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $StatePath -Force
}

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:8775/"
    Write-Host "BodyRig kører lokalt fra den verificerede checkout. Person-UI er åbnet i browseren."
} else {
    Write-Host "BodyRig kører lokalt fra den verificerede checkout. Browseråbning er sprunget over."
}
