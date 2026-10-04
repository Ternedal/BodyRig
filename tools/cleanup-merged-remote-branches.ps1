[CmdletBinding()]
param(
    [string]$Remote = "origin",
    [string]$BaseBranch = "main",
    [switch]$Apply,
    [switch]$ApplySuperseded,
    [string]$SupersededAllowList = "tools/branch-cleanup-superseded-allowlist.txt",
    [string[]]$ExtraPreserve = @()
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = @(& git @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    [pscustomobject]@{
        ExitCode = $exitCode
        Lines = @($output | ForEach-Object { [string]$_ })
        Text = (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine).Trim()
    }
}

$repo = Invoke-Git -Arguments @("rev-parse", "--show-toplevel")
if ($repo.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($repo.Text)) {
    throw "Run this script inside a Git checkout."
}
$repoRoot = $repo.Text.Trim()

$fetch = Invoke-Git -Arguments @("-C", $repoRoot, "fetch", $Remote, "--prune")
if ($fetch.ExitCode -ne 0) {
    throw "git fetch $Remote --prune failed: $($fetch.Text)"
}

$baseRef = "refs/remotes/$Remote/$BaseBranch"
$base = Invoke-Git -Arguments @("-C", $repoRoot, "rev-parse", "--verify", $baseRef)
if ($base.ExitCode -ne 0) {
    throw "Remote base ref not found: $baseRef"
}

$protectedExact = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
@(
    $BaseBranch,
    "feat/delete-unused-personality-revisions-20260919",
    "ui/photoreal-human-review-label-rebase-20261004",
    "feat/unified-brand-implementation-20260928",
    "cleanup/integrate-wsl-unc-fallback-20261004",
    "cleanup/integrate-exavatar-capture-reuse-20261004",
    "cleanup/merged-branch-pruner-20261004"
) + $ExtraPreserve | ForEach-Object {
    if (-not [string]::IsNullOrWhiteSpace($_)) {
        [void]$protectedExact.Add($_)
    }
}

$protectedPrefixes = @(
    "architecture/",
    "candidate/",
    "diagnostic/"
)

$refs = Invoke-Git -Arguments @(
    "-C", $repoRoot,
    "for-each-ref",
    "--format=%(refname:strip=3)",
    "refs/remotes/$Remote"
)
if ($refs.ExitCode -ne 0) {
    throw "Could not enumerate remote branches: $($refs.Text)"
}

$candidates = New-Object System.Collections.Generic.List[string]
$preserved = New-Object System.Collections.Generic.List[string]

foreach ($branch in @($refs.Lines | Sort-Object -Unique)) {
    $branch = ([string]$branch).Trim()
    if ([string]::IsNullOrWhiteSpace($branch) -or $branch -eq "HEAD") {
        continue
    }

    if ($protectedExact.Contains($branch) -or ($protectedPrefixes | Where-Object { $branch.StartsWith($_, [System.StringComparison]::Ordinal) })) {
        $preserved.Add($branch)
        continue
    }

    $remoteRef = "refs/remotes/$Remote/$branch"
    $merged = Invoke-Git -Arguments @(
        "-C", $repoRoot,
        "merge-base", "--is-ancestor",
        $remoteRef,
        $baseRef
    )

    if ($merged.ExitCode -eq 0) {
        $candidates.Add($branch)
    } elseif ($merged.ExitCode -ne 1) {
        throw "Could not classify $branch against $baseRef: $($merged.Text)"
    }
}

$mergedCandidateSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($candidate in $candidates) {
    [void]$mergedCandidateSet.Add($candidate)
}

$supersededCandidates = New-Object System.Collections.Generic.List[string]
$allowListPath = Join-Path $repoRoot $SupersededAllowList
if (Test-Path -LiteralPath $allowListPath -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $allowListPath -Encoding UTF8) {
        $branch = ([string]$line).Trim()
        if ([string]::IsNullOrWhiteSpace($branch) -or $branch.StartsWith("#")) {
            continue
        }
        if ($protectedExact.Contains($branch)) {
            throw "Superseded allowlist contains protected branch: $branch"
        }

        $verify = Invoke-Git -Arguments @("-C", $repoRoot, "show-ref", "--verify", "--quiet", "refs/remotes/$Remote/$branch")
        if ($verify.ExitCode -eq 0) {
            if (-not $mergedCandidateSet.Contains($branch)) {
                $supersededCandidates.Add($branch)
            }
        } elseif ($verify.ExitCode -ne 1) {
            throw "Could not verify allowlisted remote branch $branch"
        }
    }
}

Write-Host "BodyRig merged remote branch cleanup"
Write-Host "Base:      $Remote/$BaseBranch"
Write-Host "Mode:      $(if ($Apply) { 'APPLY' } else { 'DRY-RUN' })"
Write-Host "Merged candidates:      $($candidates.Count)"
Write-Host "Superseded allowlisted: $($supersededCandidates.Count)"
Write-Host "Preserved:              $($preserved.Count)"
Write-Host ""

foreach ($branch in $candidates) {
    if (-not $Apply) {
        Write-Host "[dry-run] git push $Remote --delete $branch"
        continue
    }

    $delete = Invoke-Git -Arguments @("-C", $repoRoot, "push", $Remote, "--delete", $branch)
    if ($delete.ExitCode -ne 0) {
        throw "Failed deleting $Remote/$branch: $($delete.Text)"
    }
    Write-Host "[deleted] $Remote/$branch"
}

if ($supersededCandidates.Count -gt 0) {
    Write-Host ""
    Write-Host "Reviewed superseded branches:"
    foreach ($branch in $supersededCandidates) {
        if (-not $ApplySuperseded) {
            Write-Host "[dry-run superseded] git push $Remote --delete $branch"
            continue
        }

        $delete = Invoke-Git -Arguments @("-C", $repoRoot, "push", $Remote, "--delete", $branch)
        if ($delete.ExitCode -ne 0) {
            throw "Failed deleting allowlisted superseded $Remote/$branch: $($delete.Text)"
        }
        Write-Host "[deleted superseded] $Remote/$branch"
    }
}

if (-not $Apply -and -not $ApplySuperseded) {
    Write-Host ""
    Write-Host "No branches were deleted."
    Write-Host "Use -Apply for branches already merged into origin/main."
    Write-Host "Use -ApplySuperseded separately for the exact reviewed allowlist."
}
