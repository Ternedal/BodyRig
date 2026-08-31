param(
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [ValidateRange(1, 60)][int]$RefreshSeconds = 5,
    [switch]$NoClear
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Format-Duration {
    param($Seconds)
    if ($null -eq $Seconds) { return "unknown" }
    $span = [TimeSpan]::FromSeconds([double]$Seconds)
    if ($span.TotalHours -ge 1) { return ("{0}h {1}m {2}s" -f [math]::Floor($span.TotalHours), $span.Minutes, $span.Seconds) }
    if ($span.TotalMinutes -ge 1) { return ("{0}m {1}s" -f [math]::Floor($span.TotalMinutes), $span.Seconds) }
    return ("{0}s" -f [math]::Floor($span.TotalSeconds))
}
function Score {
    param($Scores,[string]$Name)
    if ($null -eq $Scores) { return "-" }
    $property = $Scores.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) { return "-" }
    return ("{0:N3}" -f [double]$property.Value)
}

$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$progressPath = Join-Path $WorkRoot "progress.json"
Write-Host "Watching BodyRig fidelity progress: $progressPath"
Write-Host "Ctrl+C stops the watcher only; it does not stop the convergence run."

while ($true) {
    if (-not (Test-Path -LiteralPath $progressPath -PathType Leaf)) {
        Write-Host "Waiting for progress.json ..."
        Start-Sleep -Seconds $RefreshSeconds
        continue
    }
    try {
        $p = Get-Content -LiteralPath $progressPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Start-Sleep -Milliseconds 250
        continue
    }
    if (-not $NoClear) { Clear-Host }
    Write-Host "BodyRig fidelity convergence"
    Write-Host "============================"
    Write-Host "State:       $([string]$p.state)"
    Write-Host "Stage:       $([string]$p.stage)"
    Write-Host "Elapsed:     $(Format-Duration $p.elapsed_seconds)"
    Write-Host "Budget ETA:  $(Format-Duration $p.eta_seconds)"
    Write-Host "Wall budget: $([double]$p.max_wall_clock_hours)h"
    Write-Host ""
    Write-Host "Compute"
    Write-Host "  full rebuilds: $([int]$p.full_rebuilds_completed)/$([int]$p.max_full_rebuilds) | avg=$(Format-Duration $p.observed_full_rebuild_seconds_average)"
    Write-Host "  cheap refits:  $([int]$p.refinements_completed) | current=$([int]$p.current_rebuild_refinements)/$([int]$p.max_refinements_per_rebuild) | avg=$(Format-Duration $p.observed_refinement_seconds_average)"
    if ($null -ne $p.current_seed) { Write-Host "  SiTH seed:     $([int64]$p.current_seed)" }
    Write-Host ""
    Write-Host "Latest scores"
    Write-Host "  face=$(Score $p.latest_scores 'face_appearance')  body=$(Score $p.latest_scores 'body_silhouette')  hair=$(Score $p.latest_scores 'hair_appearance')"
    Write-Host "  skin=$(Score $p.latest_scores 'skin_material')  photo=$(Score $p.latest_scores 'photorealism')  plausible=$(Score $p.latest_scores 'human_plausibility')  overall=$(Score $p.latest_scores 'overall')"
    Write-Host ""
    Write-Host "Best so far"
    Write-Host "  candidate: $([string]$p.best_candidate)"
    Write-Host "  photo=$(Score $p.best_scores 'photorealism')  plausible=$(Score $p.best_scores 'human_plausibility')  overall=$(Score $p.best_scores 'overall')"
    Write-Host "  strategy=$([string]$p.strategy) | next=$([string]$p.next_focus)"
    if (-not [string]::IsNullOrWhiteSpace([string]$p.best_preview_dir)) {
        Write-Host "  preview: $(Join-Path $WorkRoot ([string]$p.best_preview_dir))"
    }
    Write-Host ""
    Write-Host "Updated: $([string]$p.last_update)"
    if ([string]$p.state -in @("completed", "error")) { break }
    Start-Sleep -Seconds $RefreshSeconds
}
