$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script = Join-Path $repoRoot "clone-body.ps1"
$root = Join-Path ([System.IO.Path]::GetTempPath()) ("bodyrig-clone-override-test-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $root | Out-Null
try {
    $source = Join-Path $root "source.mp4"
    [System.IO.File]::WriteAllBytes($source, [byte[]](1,2,3))
    $segment = Join-Path $root "segment.mp4"
    [System.IO.File]::WriteAllBytes($segment, [byte[]](4,5,6))
    $fourD = Join-Path $root "4d"
    New-Item -ItemType Directory -Path $fourD | Out-Null
    $externalPython = Join-Path $root "external-python"
    $identityConfig = Join-Path $root "identity.json"
    $fitterConfig = Join-Path $root "fitter.json"
    Set-Content -LiteralPath $externalPython -Value "stub" -NoNewline
    Set-Content -LiteralPath $identityConfig -Value "{}" -NoNewline
    Set-Content -LiteralPath $fitterConfig -Value "{}" -NoNewline

    $sourceManifest = Join-Path $root "sources.json"
    @{
        format = "bodyrig-stash-source-manifest"
        version = 1
        source_kind = "stash-local"
        performer = @{ id = "7"; name = "Alice"; disambiguation = "" }
        stash_version = "test"
        candidate_count = 1
        selected = @(@{
            scene_id = "11"; scene_title = "Scene"; path = $source
            width = 1920; height = 1080; duration = 30.0; framerate = 30.0
            performer_count = 1; score = 100.0
        })
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $sourceManifest -Encoding UTF8

    $override = Join-Path $root "segments.json"
    @{
        format = "bodyrig-observation-segments"
        version = 1
        selection_sha256 = ("a" * 64)
        segments = @(@{
            source_id = "s001"; scene_id = "11"; path = $segment
            start_seconds = 1.0; duration_seconds = 5.0; sha256 = ("0" * 64)
        })
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $override -Encoding UTF8

    $output = Join-Path $root "out"
    $messages = @()
    try {
        & $script `
            -SourceManifest $sourceManifest `
            -SourceOverrideManifest $override `
            -ExternalPython $externalPython `
            -FourDHumansRepo $fourD `
            -IdentityCaptureConfig $identityConfig `
            -FitterConfig $fitterConfig `
            -BodyId "alice" `
            -Name "Alice" `
            -OutputDir $output 2>&1 | ForEach-Object { $messages += [string]$_ }
        throw "Expected clone-body.ps1 to reject a tampered observation segment."
    } catch {
        $messages += [string]$_.Exception.Message
    }
    $joined = $messages -join "`n"
    if ($joined -notmatch "Observation segment SHA-256 mismatch") {
        throw "Tamper gate did not fail for the expected reason. Output:`n$joined"
    }
    if (Test-Path -LiteralPath $output) {
        throw "clone-body.ps1 created clone output before rejecting the tampered segment."
    }

    Write-Host "Observation segment tamper gate: PASS"
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
