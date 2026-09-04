param(
    [string]$JobId = "",
    [ValidateRange(1, 300)]
    [int]$IntervalSeconds = 5,
    [switch]$Once,
    [switch]$NoClear
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-BodyRigDataRoot {
    $configured = [string][Environment]::GetEnvironmentVariable("BODYRIG_DATA_DIR")
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return [System.IO.Path]::GetFullPath($configured)
    }
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "BodyRig data root kan ikke findes: BODYRIG_DATA_DIR og LOCALAPPDATA mangler."
    }
    return Join-Path $env:LOCALAPPDATA "BodyRig"
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Kunne ikke læse JSON: $Path"
    }
}

function Read-TailText {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Lines = 20
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return "" }
    try {
        return (@(Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction Stop) -join "`n")
    } catch {
        return ""
    }
}

function Format-Duration {
    param([double]$Seconds)
    $value = [Math]::Max(0, [int][Math]::Round($Seconds))
    $hours = [Math]::Floor($value / 3600)
    $minutes = [Math]::Floor(($value % 3600) / 60)
    $seconds = $value % 60
    if ($hours -gt 0) { return "{0}t {1}m {2}s" -f $hours, $minutes, $seconds }
    if ($minutes -gt 0) { return "{0}m {1}s" -f $minutes, $seconds }
    return "{0}s" -f $seconds
}

function Resolve-BodyJob {
    param([Parameter(Mandatory = $true)][string]$JobsRoot)

    if (-not [string]::IsNullOrWhiteSpace($JobId)) {
        if ($JobId -notmatch '^job-[0-9a-f]{32}$') {
            throw "JobId har ugyldigt format: $JobId"
        }
        $root = Join-Path $JobsRoot $JobId
        $path = Join-Path $root "job.json"
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "BodyRig-job findes ikke: $JobId"
        }
        $job = Read-JsonFile -Path $path
        if ([string]$job.kind -ne "body-build") {
            throw "Jobbet er ikke et body-build: $JobId"
        }
        return [pscustomobject]@{ Root = $root; Job = $job }
    }

    $candidates = @(
        Get-ChildItem -LiteralPath $JobsRoot -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                $path = Join-Path $_.FullName "job.json"
                if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return }
                try { $job = Read-JsonFile -Path $path } catch { return }
                if ([string]$job.kind -ne "body-build") { return }
                $created = [DateTimeOffset]::MinValue
                [void][DateTimeOffset]::TryParse([string]$job.created_utc, [ref]$created)
                [pscustomobject]@{
                    Root = $_.FullName
                    Job = $job
                    Created = $created
                    Active = @("queued", "running") -contains [string]$job.status
                }
            }
    )
    if ($candidates.Count -eq 0) {
        throw "Ingen BodyRig body-build jobs fundet."
    }
    $selected = $candidates |
        Sort-Object @{ Expression = "Active"; Descending = $true }, @{ Expression = "Created"; Descending = $true } |
        Select-Object -First 1
    return [pscustomobject]@{ Root = $selected.Root; Job = $selected.Job }
}

function Convert-WslMountPathToWindows {
    param([Parameter(Mandatory = $true)][string]$Path)
    $match = [regex]::Match($Path, '^/mnt/([A-Za-z])/(.+)$')
    if (-not $match.Success) { return $null }
    $drive = $match.Groups[1].Value.ToUpperInvariant()
    $tail = $match.Groups[2].Value.Replace('/', '\')
    return "$drive`:\$tail"
}

function Get-CheckpointProgress {
    param([Parameter(Mandatory = $true)][string[]]$Sources)

    $roots = New-Object System.Collections.Generic.List[string]
    foreach ($source in $Sources) {
        $windowsSource = Convert-WslMountPathToWindows -Path $source
        if ([string]::IsNullOrWhiteSpace($windowsSource)) { continue }
        $parent = Split-Path -Parent $windowsSource
        if ([string]::IsNullOrWhiteSpace($parent)) { continue }
        $root = Join-Path $parent "bodyrig-recovery-checkpoints"
        if ((Test-Path -LiteralPath $root -PathType Container) -and -not $roots.Contains($root)) {
            $roots.Add($root)
        }
    }
    if ($roots.Count -eq 0) { return $null }

    $statuses = @(
        foreach ($root in $roots) {
            Get-ChildItem -LiteralPath $root -Filter "segment-*.status.json" -File -ErrorAction SilentlyContinue |
                ForEach-Object {
                    try { $value = Read-JsonFile -Path $_.FullName } catch { return }
                    if ([string]$value.format -ne "bodyrig-recovery-segment-status") { return }
                    if ($null -eq $value.source_index) { return }
                    [pscustomobject]@{
                        Root = $root
                        Path = $_.FullName
                        SourceIndex = [int]$value.source_index
                        State = [string]$value.state
                        Detail = [string]$value.detail
                    }
                }
        }
    )
    if ($statuses.Count -eq 0) { return $null }

    $running = @($statuses | Where-Object { $_.State -eq "running" } | Sort-Object SourceIndex | Select-Object -Last 1)
    $failed = @($statuses | Where-Object { $_.State -eq "failed" } | Sort-Object SourceIndex | Select-Object -Last 1)
    $completed = @($statuses | Where-Object { $_.State -eq "complete" } | Select-Object -ExpandProperty SourceIndex -Unique).Count
    $current = if ($running.Count -gt 0) { $running[0] } elseif ($failed.Count -gt 0) { $failed[0] } else { $null }

    $liveLogPath = ""
    $liveTail = ""
    $logModified = $null
    if ($null -ne $current) {
        $prefix = "segment-{0:D2}" -f ($current.SourceIndex + 1)
        $liveLogPath = Join-Path $current.Root "$prefix.log"
        $liveTail = Read-TailText -Path $liveLogPath -Lines 80
        if (Test-Path -LiteralPath $liveLogPath -PathType Leaf) {
            $logModified = (Get-Item -LiteralPath $liveLogPath).LastWriteTime
        }
    }

    return [pscustomobject]@{
        CurrentSegment = if ($null -ne $current) { $current.SourceIndex + 1 } else { $null }
        CurrentState = if ($null -ne $current) { $current.State } else { "complete" }
        CompletedSegments = $completed
        CheckpointRoots = @($roots)
        LiveLogPath = $liveLogPath
        LiveLogModified = $logModified
        Tail = $liveTail
    }
}

function Get-RecoveryStage {
    param([Parameter(Mandatory = $true)]$Job)

    $personId = [string]$Job.person_id
    if ([string]::IsNullOrWhiteSpace($personId)) { return $null }
    $tempRoot = [System.IO.Path]::GetTempPath()
    $candidates = @(
        Get-ChildItem -LiteralPath $tempRoot -Directory -Filter "bodyrig-wsl-recovery-*" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending
    )
    foreach ($candidate in $candidates) {
        $requestPath = Join-Path $candidate.FullName "request.json"
        if (-not (Test-Path -LiteralPath $requestPath -PathType Leaf)) { continue }
        try { $request = Read-JsonFile -Path $requestPath } catch { continue }
        $sources = @($request.sources | ForEach-Object { [string]$_ })
        if ($sources.Count -eq 0) { continue }
        if (-not ($sources | Where-Object { $_ -like "*$personId*" })) { continue }

        $stderrPath = Join-Path $candidate.FullName "stderr.log"
        $statusPath = Join-Path $candidate.FullName "status.json"
        $stderr = Read-TailText -Path $stderrPath -Lines 120
        $checkpoint = Get-CheckpointProgress -Sources $sources

        $segmentMatches = @([regex]::Matches($stderr, 'Saving tracks at\s*:\s*.*?segment-(\d+)', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase))
        $completedMatches = @([regex]::Matches($stderr, 'Tracking\s*:\s*segment-(\d+).*?100%', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase))
        $fallbackCurrent = $null
        if ($segmentMatches.Count -gt 0) {
            $fallbackCurrent = [int]$segmentMatches[-1].Groups[1].Value + 1
        }
        $fallbackCompleted = @($completedMatches | ForEach-Object { [int]$_.Groups[1].Value } | Sort-Object -Unique).Count

        $status = $null
        if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
            try { $status = Read-JsonFile -Path $statusPath } catch { $status = $null }
        }

        $stderrModified = $null
        if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
            $stderrModified = (Get-Item -LiteralPath $stderrPath).LastWriteTime
        }

        $currentSegment = if ($null -ne $checkpoint -and $null -ne $checkpoint.CurrentSegment) { $checkpoint.CurrentSegment } else { $fallbackCurrent }
        $completedSegments = if ($null -ne $checkpoint) { $checkpoint.CompletedSegments } else { $fallbackCompleted }
        $tail = if ($null -ne $checkpoint -and -not [string]::IsNullOrWhiteSpace([string]$checkpoint.Tail)) { [string]$checkpoint.Tail } else { $stderr }
        $progressSource = if ($null -ne $checkpoint) { "checkpoint" } else { "staging" }

        return [pscustomobject]@{
            Root = $candidate.FullName
            SourceCount = $sources.Count
            CurrentSegment = $currentSegment
            CurrentState = if ($null -ne $checkpoint) { $checkpoint.CurrentState } else { "unknown" }
            CompletedSegments = $completedSegments
            ProgressSource = $progressSource
            StderrPath = $stderrPath
            StderrModified = $stderrModified
            LiveLogPath = if ($null -ne $checkpoint) { $checkpoint.LiveLogPath } else { "" }
            LiveLogModified = if ($null -ne $checkpoint) { $checkpoint.LiveLogModified } else { $null }
            Status = $status
            Tail = $tail
        }
    }
    return $null
}

function Get-WslDistribution {
    param([string]$LogText)
    $match = [regex]::Match($LogText, 'Recovery transport:\s*WSL\s+([^\r\n]+)')
    if ($match.Success) { return $match.Groups[1].Value.Trim() }
    return "Ubuntu-22.04"
}

function Get-GpuSnapshot {
    param([Parameter(Mandatory = $true)][string]$Distribution)
    try {
        $raw = @(& wsl.exe -d $Distribution -- nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu --format=csv,noheader,nounits 2>$null)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -lt 1) { return $null }
        $parts = @(([string]$raw[0]).Split(',') | ForEach-Object { $_.Trim() })
        if ($parts.Count -lt 5) { return $null }
        return [pscustomobject]@{
            Utilization = $parts[0]
            MemoryUsed = $parts[1]
            MemoryTotal = $parts[2]
            Power = $parts[3]
            Temperature = $parts[4]
        }
    } catch {
        return $null
    }
}

function Get-Phase {
    param(
        [Parameter(Mandatory = $true)]$Job,
        [Parameter(Mandatory = $true)][string]$LogText
    )
    $clone = [string]$Job.clone_output
    $acceptance = [string]$Job.acceptance_dir
    $fidelity = [string]$Job.fidelity_dir
    if ([string]$Job.status -eq "succeeded") { return "complete" }
    if (-not [string]::IsNullOrWhiteSpace($fidelity) -and (Test-Path -LiteralPath (Join-Path $fidelity "review.json") -PathType Leaf)) { return "registering" }
    if (-not [string]::IsNullOrWhiteSpace($fidelity) -and (Test-Path -LiteralPath $fidelity -PathType Container)) { return "fidelity-review" }
    if (-not [string]::IsNullOrWhiteSpace($acceptance) -and (Test-Path -LiteralPath (Join-Path $acceptance "bodyrig-acceptance.json") -PathType Leaf)) { return "gate-a-complete" }
    if (-not [string]::IsNullOrWhiteSpace($acceptance) -and (Test-Path -LiteralPath $acceptance -PathType Container)) { return "gate-a" }
    if ($LogText -like "*BodyRig Stash clone: PASS*") { return "clone-complete" }
    if (-not [string]::IsNullOrWhiteSpace($clone) -and (Test-Path -LiteralPath (Join-Path $clone "bodyrig-observation-evidence.json") -PathType Leaf)) { return "recovery" }
    if (-not [string]::IsNullOrWhiteSpace($clone) -and (Test-Path -LiteralPath (Join-Path $clone "bodyrig-stash-source-manifest.json") -PathType Leaf)) { return "sources-selected" }
    if ($LogText -like "*Starting Stash clone pipeline.*") { return "source-selection" }
    if ($LogText -like "*Live readiness: PASS*") { return "readiness-complete" }
    if ($LogText -like "*BodyRig rig readiness: READY*") { return "readiness" }
    return [string]$Job.status
}

$dataRoot = Get-BodyRigDataRoot
$jobsRoot = Join-Path $dataRoot "ui-jobs"
if (-not (Test-Path -LiteralPath $jobsRoot -PathType Container)) {
    throw "BodyRig ui-jobs mappe findes ikke: $jobsRoot"
}

while ($true) {
    $resolved = Resolve-BodyJob -JobsRoot $jobsRoot
    $jobPath = Join-Path $resolved.Root "job.json"
    $job = Read-JsonFile -Path $jobPath
    $logPath = [string]$job.log_path
    $logText = Read-TailText -Path $logPath -Lines 120
    $phase = Get-Phase -Job $job -LogText $logText
    $recovery = Get-RecoveryStage -Job $job

    $elapsed = 0.0
    $started = [DateTimeOffset]::MinValue
    if ([DateTimeOffset]::TryParse([string]$job.started_utc, [ref]$started)) {
        $end = [DateTimeOffset]::Now
        $completed = [DateTimeOffset]::MinValue
        if (-not [string]::IsNullOrWhiteSpace([string]$job.completed_utc) -and [DateTimeOffset]::TryParse([string]$job.completed_utc, [ref]$completed)) {
            $end = $completed
        }
        $elapsed = [Math]::Max(0, ($end - $started).TotalSeconds)
    }

    if (-not $NoClear) { Clear-Host }
    Write-Host "BodyRig physical body-build monitor"
    Write-Host "Job:      $($job.job_id)"
    Write-Host "Status:   $($job.status)"
    Write-Host "Phase:    $phase"
    Write-Host "Revision: $($job.bodyrig_revision)"
    Write-Host "Elapsed:  $(Format-Duration -Seconds $elapsed)"

    if ($recovery) {
        Write-Host ""
        if ($null -ne $recovery.CurrentSegment) {
            Write-Host "Recovery: segment $($recovery.CurrentSegment)/$($recovery.SourceCount) | completed: $($recovery.CompletedSegments) | state: $($recovery.CurrentState)"
        } else {
            Write-Host "Recovery: staging aktiv | sources: $($recovery.SourceCount) | completed: $($recovery.CompletedSegments)"
        }
        Write-Host "Progress authority: $($recovery.ProgressSource)"
        Write-Host "Staging:  $($recovery.Root)"
        if (-not [string]::IsNullOrWhiteSpace([string]$recovery.LiveLogPath)) {
            Write-Host "Segment log: $($recovery.LiveLogPath)"
        }
        if ($null -ne $recovery.LiveLogModified) {
            Write-Host "Segment log sidst ændret: $($recovery.LiveLogModified)"
        } elseif ($null -ne $recovery.StderrModified) {
            Write-Host "Recovery log sidst ændret: $($recovery.StderrModified)"
        }
        if ($null -ne $recovery.Status) {
            Write-Host "Recovery completion status: returncode=$($recovery.Status.returncode)"
        }

        $distribution = Get-WslDistribution -LogText $logText
        $gpu = Get-GpuSnapshot -Distribution $distribution
        if ($gpu) {
            Write-Host "GPU:      $($gpu.Utilization)% | VRAM $($gpu.MemoryUsed)/$($gpu.MemoryTotal) MiB | $($gpu.Power) W | $($gpu.Temperature) C"
        }

        $interesting = @(
            $recovery.Tail -split "`r?`n" |
                Where-Object {
                    $_ -match 'Number of frames|Saving tracks at|Tracking\s*:|BodyRig recovery VRAM|Loading Predictor model|Loading Detection model'
                } |
                Select-Object -Last 12
        )
        if ($interesting.Count -gt 0) {
            Write-Host ""
            Write-Host "=== RECOVERY PROGRESS ==="
            $interesting | ForEach-Object { Write-Host $_ }
        }
    }

    $mainTail = @($logText -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Last 12)
    if ($mainTail.Count -gt 0) {
        Write-Host ""
        Write-Host "=== JOB LOG ==="
        $mainTail | ForEach-Object { Write-Host $_ }
    }

    if ($Once -or @("succeeded", "failed", "canceled", "interrupted") -contains [string]$job.status) {
        break
    }
    Start-Sleep -Seconds $IntervalSeconds
}
