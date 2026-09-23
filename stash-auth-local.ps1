Set-StrictMode -Version Latest

function Test-BodyRigStashConfigV1 {
    param($Value)
    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }
    try { return [decimal]$Value -eq [decimal]1 } catch { return $false }
}

function Import-BodyRigSavedStashAuth {
    param(
        [string]$ExpectedUrl = "",
        [string]$ApiKeyEnv = "STASH_API_KEY"
    )

    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        throw "Saved BodyRig Stash authentication is Windows-only."
    }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "LOCALAPPDATA is required for saved BodyRig Stash authentication."
    }
    if ($ApiKeyEnv -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "Stash API-key environment variable name is invalid."
    }

    $configPath = Join-Path $env:LOCALAPPDATA "BodyRig\config\stash.json"
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "Saved Stash config is missing: $configPath"
    }
    try {
        $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Saved Stash config is unreadable JSON."
    }
    if ([string]$config.format -ne "bodyrig-local-stash-config" -or -not (Test-BodyRigStashConfigV1 $config.version)) {
        throw "Saved Stash config has an unexpected format/version."
    }

    $savedUrl = ([string]$config.url).Trim()
    $protectedKey = [string]$config.api_key_dpapi
    if ([string]::IsNullOrWhiteSpace($savedUrl) -or [string]::IsNullOrWhiteSpace($protectedKey)) {
        throw "Saved Stash config lacks URL or protected API key."
    }
    try { $savedUri = [Uri]$savedUrl }
    catch { throw "Saved Stash URL is invalid." }
    if (
        $savedUri.Scheme -notin @("http", "https") -or
        [string]::IsNullOrWhiteSpace($savedUri.Host) -or
        -not [string]::IsNullOrWhiteSpace($savedUri.UserInfo) -or
        -not [string]::IsNullOrWhiteSpace($savedUri.Query) -or
        -not [string]::IsNullOrWhiteSpace($savedUri.Fragment)
    ) {
        throw "Saved Stash URL is not a canonical credential-free http(s) base URL."
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedUrl)) {
        try { $expectedUri = [Uri]$ExpectedUrl.Trim() }
        catch { throw "Requested Stash URL is invalid." }
        $savedBase = $savedUri.AbsoluteUri.TrimEnd('/')
        $expectedBase = $expectedUri.AbsoluteUri.TrimEnd('/')
        if (-not [string]::Equals($savedBase, $expectedBase, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Requested Stash URL differs from saved BodyRig Stash authority."
        }
    }

    $secure = ConvertTo-SecureString $protectedKey
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $apiKey = $null
    try {
        $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        if ([string]::IsNullOrWhiteSpace($apiKey)) {
            throw "Saved Stash API key could not be decrypted for this Windows user."
        }
        [Environment]::SetEnvironmentVariable("STASH_URL", $savedUrl, "Process")
        [Environment]::SetEnvironmentVariable($ApiKeyEnv, $apiKey, "Process")
    } finally {
        $apiKey = $null
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }

    return $savedUrl
}
