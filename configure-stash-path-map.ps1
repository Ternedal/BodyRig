param(
    [string]$ConfigPath = "",
    [string]$PeopleDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    return
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA er ikke tilgængelig; BodyRig kan ikke auto-konfigurere Stash paths."
}

$bodyRigRoot = Join-Path $env:LOCALAPPDATA "BodyRig"
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $bodyRigRoot "config\stash.json"
}
if ([string]::IsNullOrWhiteSpace($PeopleDir)) {
    $PeopleDir = Join-Path $bodyRigRoot "people"
}

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    Write-Host "BodyRig Stash path map: ingen gemt Stash-konfiguration; springer over."
    return
}
if (-not (Test-Path -LiteralPath $PeopleDir -PathType Container)) {
    Write-Host "BodyRig Stash path map: ingen Person-profiler endnu; springer over."
    return
}

try {
    $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    throw "BodyRig Stash path map: gemt Stash-konfiguration er ulæselig."
}
if ([string]$config.format -ne "bodyrig-local-stash-config" -or [int]$config.version -ne 1) {
    throw "BodyRig Stash path map: gemt Stash-konfiguration har forkert format/version."
}
$stashUrl = [string]$config.url
$protectedKey = [string]$config.api_key_dpapi
if ([string]::IsNullOrWhiteSpace($stashUrl) -or [string]::IsNullOrWhiteSpace($protectedKey)) {
    throw "BodyRig Stash path map: gemt Stash-konfiguration mangler URL eller krypteret API-key."
}

try {
    $stashUri = [Uri]$stashUrl
} catch {
    throw "BodyRig Stash path map: gemt Stash URL er ugyldig."
}
$hostName = [string]$stashUri.Host
if ([string]::IsNullOrWhiteSpace($hostName)) {
    throw "BodyRig Stash path map: Stash URL mangler host."
}
$graphqlUrl = $stashUrl.TrimEnd('/') + "/graphql"

$secure = ConvertTo-SecureString $protectedKey
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "BodyRig Stash path map: API-key kunne ikke dekrypteres for denne Windows-bruger."
}

function Invoke-StashGraphQl {
    param(
        [Parameter(Mandatory = $true)][string]$Query,
        [Parameter(Mandatory = $true)][hashtable]$Variables
    )
    $payload = [ordered]@{ query = $Query; variables = $Variables } | ConvertTo-Json -Depth 12 -Compress
    $headers = @{ ApiKey = $apiKey }
    $response = Invoke-RestMethod -Method Post -Uri $graphqlUrl -Headers $headers -ContentType "application/json" -Body $payload -TimeoutSec 30
    if ($null -ne $response.errors -and @($response.errors).Count -gt 0) {
        $message = (@($response.errors) | ForEach-Object { [string]$_.message }) -join "; "
        throw "Stash GraphQL error: $message"
    }
    return $response.data
}

$performerIds = @(
    Get-ChildItem -LiteralPath $PeopleDir -Filter "*.json" -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                $profile = Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            } catch {
                return
            }
            if ([string]$profile.source.kind -eq "stash-performer" -and -not [string]::IsNullOrWhiteSpace([string]$profile.source.performer_id)) {
                [string]$profile.source.performer_id
            }
        } |
        Sort-Object -Unique
)
if ($performerIds.Count -eq 0) {
    Write-Host "BodyRig Stash path map: ingen Stash-bundne personer endnu; springer over."
    return
}

$currentQuery = @'
query BodyRigPathDiscovery($id: ID!, $limit: Int!) {
  findScenes(
    scene_filter: {performers: {value: [$id], modifier: INCLUDES}}
    filter: {page: 1, per_page: $limit, sort: "created_at", direction: DESC}
  ) {
    scenes { files { path } performers { id } }
  }
}
'@
$legacyQuery = @'
query BodyRigPathDiscoveryLegacy($id: ID!, $limit: Int!) {
  findScenes(
    scene_filter: {performer_id: $id}
    filter: {page: 1, per_page: $limit, sort: "created_at", direction: DESC}
  ) {
    scenes { files { path } performers { id } }
  }
}
'@

$rawPaths = New-Object System.Collections.Generic.List[string]
foreach ($performerId in $performerIds) {
    $variables = @{ id = $performerId; limit = 200 }
    try {
        $data = Invoke-StashGraphQl -Query $currentQuery -Variables $variables
    } catch {
        $data = Invoke-StashGraphQl -Query $legacyQuery -Variables $variables
    }
    foreach ($scene in @($data.findScenes.scenes)) {
        $scenePerformerIds = @($scene.performers | ForEach-Object { [string]$_.id })
        if ($scenePerformerIds -notcontains [string]$performerId) { continue }
        foreach ($file in @($scene.files)) {
            $path = [string]$file.path
            if (-not [string]::IsNullOrWhiteSpace($path) -and $path -match '^[A-Za-z]:[\\/]') {
                $rawPaths.Add($path.Replace('/', '\'))
            }
        }
    }
}
$rawPaths = @($rawPaths | Sort-Object -Unique)
if ($rawPaths.Count -eq 0) {
    throw "BodyRig Stash path map: Stash-returnerede scener har ingen Windows file paths at mappe."
}

$mapping = [ordered]@{}
$proof = @()
$driveGroups = $rawPaths | Group-Object { $_.Substring(0, 1).ToUpperInvariant() }
foreach ($driveGroup in $driveGroups) {
    $drive = [string]$driveGroup.Name
    $shareRoot = "\\$hostName\VR_$drive"
    if (-not (Test-Path -LiteralPath $shareRoot -PathType Container)) {
        continue
    }

    $prefixes = New-Object System.Collections.Generic.HashSet[string]([System.StringComparer]::OrdinalIgnoreCase)
    [void]$prefixes.Add("$drive`:\")
    foreach ($rawPath in @($driveGroup.Group)) {
        $relative = $rawPath.Substring(3)
        $parts = @($relative.Split('\', [System.StringSplitOptions]::RemoveEmptyEntries))
        $directoryCount = [Math]::Max(0, $parts.Count - 1)
        $maxDepth = [Math]::Min(4, $directoryCount)
        for ($depth = 1; $depth -le $maxDepth; $depth++) {
            $prefix = "$drive`:\" + (($parts[0..($depth - 1)]) -join '\')
            [void]$prefixes.Add($prefix)
        }
    }

    $bestPrefix = $null
    $bestHits = -1
    $bestCoverage = -1
    foreach ($prefix in $prefixes) {
        $hits = 0
        $coverage = 0
        foreach ($rawPath in @($driveGroup.Group)) {
            if (-not ($rawPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase))) { continue }
            $boundaryOk = $rawPath.Length -eq $prefix.Length -or $prefix.EndsWith('\') -or $rawPath[$prefix.Length] -eq '\'
            if (-not $boundaryOk) { continue }
            $coverage++
            $remainder = $rawPath.Substring($prefix.Length).TrimStart('\')
            $candidate = if ([string]::IsNullOrWhiteSpace($remainder)) { $shareRoot } else { Join-Path $shareRoot $remainder }
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $hits++ }
        }
        if ($hits -gt $bestHits -or ($hits -eq $bestHits -and $coverage -gt $bestCoverage)) {
            $bestPrefix = [string]$prefix
            $bestHits = $hits
            $bestCoverage = $coverage
        }
    }

    if ($bestHits -gt 0 -and -not [string]::IsNullOrWhiteSpace($bestPrefix)) {
        $mapping[$bestPrefix.TrimEnd('\')] = $shareRoot
        $proof += [ordered]@{
            drive = $drive
            source_prefix = $bestPrefix.TrimEnd('\')
            share = $shareRoot
            verified_files = $bestHits
            candidate_files = $bestCoverage
        }
    }
}

if ($mapping.Count -eq 0) {
    $roots = @($rawPaths | ForEach-Object {
        if ($_ -match '^([A-Za-z]):\\([^\\]+)') { "$($matches[1].ToUpperInvariant()):\$($matches[2])" }
        else { $_.Substring(0, [Math]::Min($_.Length, 32)) }
    } | Sort-Object -Unique)
    throw "BodyRig Stash path map: kunne ikke bevise en læsbar SMB-mapping for Stash paths. Returnerede roots: $($roots -join ', '). Forventede shares på $hostName med navne som VR_E/VR_F."
}

$mapJson = $mapping | ConvertTo-Json -Compress
$env:BODYRIG_STASH_PATH_MAP = $mapJson
[Environment]::SetEnvironmentVariable("BODYRIG_STASH_PATH_MAP", $mapJson, [EnvironmentVariableTarget]::User)

$evidencePath = Join-Path $bodyRigRoot "config\stash-path-map.json"
$evidence = [ordered]@{
    format = "bodyrig-local-stash-path-map"
    version = 1
    stash_host = $hostName
    mapping = $mapping
    proof = $proof
    updated_utc = [DateTime]::UtcNow.ToString("o")
}
$temp = "$evidencePath.tmp-$([Guid]::NewGuid().ToString('N'))"
[System.IO.File]::WriteAllText($temp, (($evidence | ConvertTo-Json -Depth 8) + "`n"), [System.Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temp -Destination $evidencePath -Force

Write-Host "BodyRig Stash path map: READY"
foreach ($item in $proof) {
    Write-Host "  $($item.source_prefix) -> $($item.share) | verified files: $($item.verified_files)/$($item.candidate_files)"
}
