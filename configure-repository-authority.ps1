param(
    [switch]$Apply,
    [switch]$ReplaceExistingProtection
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RequiredStatusCheckAppId = 15368
$RequiredStatusChecks = @(
    "test (3.11)",
    "test (3.12)",
    "test-windows-python",
    "acceptance-windows",
    "adapter-log-handle",
    "analyze (python)"
)

function Need-Revision {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $normalized = $Value.Trim().ToLowerInvariant()
    if ($normalized -notmatch '^[0-9a-f]{40}$') {
        throw "$Label is not an exact Git revision."
    }
    return $normalized
}

function Invoke-GhJson {
    param(
        [Parameter(Mandatory = $true)][string]$ApiPath,
        [switch]$AllowFailure
    )

    $raw = @(& gh api $ApiPath 2>&1)
    if ($LASTEXITCODE -ne 0) {
        if ($AllowFailure) { return $null }
        throw "GitHub API read failed for repository-authority endpoint: $ApiPath"
    }

    $text = $raw -join "`n"
    try { return ($text | ConvertFrom-Json -Depth 60) }
    catch { throw "GitHub API returned unreadable JSON for repository-authority endpoint: $ApiPath" }
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "PowerShell 7+ (pwsh) is required."
}

$repoRoot = (Resolve-Path $PSScriptRoot).Path
$branchRaw = @(& git -C $repoRoot branch --show-current 2>&1)
if ($LASTEXITCODE -ne 0 -or $branchRaw.Count -ne 1 -or ([string]$branchRaw[0]).Trim() -ne "main") {
    throw "Repository-authority configuration must run from branch main."
}

$dirty = @(& git -C $repoRoot status --porcelain 2>&1)
if ($LASTEXITCODE -ne 0 -or $dirty.Count -gt 0) {
    throw "Repository-authority configuration requires an exact clean main checkout."
}

$headRaw = @(& git -C $repoRoot rev-parse HEAD 2>&1)
if ($LASTEXITCODE -ne 0 -or $headRaw.Count -ne 1) {
    throw "Could not resolve BodyRig HEAD."
}
$head = Need-Revision -Value ([string]$headRaw[0]) -Label "BodyRig HEAD"

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    throw "GitHub CLI (gh) is required to configure repository authority."
}
@(& gh auth status -h github.com 2>&1) | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated for github.com."
}

$branch = Invoke-GhJson -ApiPath "repos/Ternedal/BodyRig/branches/main"
$githubHead = Need-Revision -Value ([string]$branch.commit.sha) -Label "GitHub main HEAD"
if ([string]$branch.name -ne "main") {
    throw "GitHub branch payload is not main."
}
if ($githubHead -cne $head) {
    throw "GitHub main does not match the exact local checkout. Expected $head, got $githubHead."
}

$rulesetPayload = Invoke-GhJson -ApiPath "repos/Ternedal/BodyRig/rulesets?includes_parents=true"
$rulesets = if ($null -eq $rulesetPayload) { @() } else { @($rulesetPayload) }
if ($rulesets.Count -gt 0) {
    throw "Existing repository rulesets detected. Refusing to compose classic protection automatically; review the live rulesets and use verify-repository-authority.ps1."
}

$classic = Invoke-GhJson -ApiPath "repos/Ternedal/BodyRig/branches/main/protection" -AllowFailure
if ($null -ne $classic -and -not $ReplaceExistingProtection) {
    throw "Classic branch protection already exists. Refusing to replace it without -ReplaceExistingProtection."
}

$checks = @()
foreach ($name in $RequiredStatusChecks) {
    $checks += [ordered]@{
        context = $name
        app_id = $RequiredStatusCheckAppId
    }
}

$payload = [ordered]@{
    required_status_checks = [ordered]@{
        strict = $true
        checks = $checks
    }
    enforce_admins = $true
    required_pull_request_reviews = [ordered]@{
        dismiss_stale_reviews = $false
        require_code_owner_reviews = $false
        required_approving_review_count = 0
        require_last_push_approval = $false
    }
    restrictions = $null
    required_linear_history = $false
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $false
    required_conversation_resolution = $true
    lock_branch = $false
    allow_fork_syncing = $false
}

$payloadJson = $payload | ConvertTo-Json -Depth 20

if (-not $Apply) {
    Write-Host "BodyRig repository authority configuration: DRY RUN"
    Write-Host "Repository: Ternedal/BodyRig"
    Write-Host "Branch:     main"
    Write-Host "Head:       $head"
    Write-Host "Mode:       classic branch protection"
    Write-Host "Required check source: GitHub Actions app $RequiredStatusCheckAppId"
    Write-Host "Required approving reviews: 0 (PR still required)"
    Write-Host "Payload:"
    Write-Host $payloadJson
    Write-Host "No repository setting was changed. Re-run with -Apply using a GitHub identity with repository Administration: write."
    exit 0
}

$tempPath = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-repository-protection-" + [Guid]::NewGuid().ToString("N") + ".json")
try {
    $payloadJson | Set-Content -LiteralPath $tempPath -Encoding utf8NoBOM

    @(& gh api `
        --method PUT `
        -H "Accept: application/vnd.github+json" `
        -H "X-GitHub-Api-Version: 2026-03-10" `
        "repos/Ternedal/BodyRig/branches/main/protection" `
        --input $tempPath 2>&1) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub branch-protection update failed. The authenticated gh identity must have repository Administration: write."
    }
}
finally {
    if (Test-Path -LiteralPath $tempPath -PathType Leaf) {
        Remove-Item -LiteralPath $tempPath -Force
    }
}

$verifier = Join-Path $repoRoot "verify-repository-authority.ps1"
if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
    throw "Repository-authority verifier is missing after protection write: $verifier"
}

Write-Host "BodyRig repository protection write completed; running live checkout-bound verifier."
& $verifier
$verifyExit = $LASTEXITCODE
if ($verifyExit -ne 0) {
    throw "Protection was written, but verify-repository-authority.ps1 did not PASS. Leave protection in place and inspect the verifier output; do not infer repository authority."
}

Write-Host "BodyRig repository authority configuration: PASS"
Write-Host "Authority: repository settings only; no physical acceptance, candidate promotion, or production activation."
exit 0
