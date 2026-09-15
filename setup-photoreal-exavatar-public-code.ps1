param(
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxDependencyRoot = "/opt/bodyrig-exavatar/deps",
    [string]$WslExe = "wsl.exe",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repos = @(
    [ordered]@{ Name = "ExAvatar_RELEASE"; Url = "https://github.com/mks0601/ExAvatar_RELEASE.git"; Commit = "d45268730c779fae4118f1a361cf9ff639bc4d1e" },
    [ordered]@{ Name = "DECA"; Url = "https://github.com/yfeng95/DECA.git"; Commit = "a11554ae2a2b0f3998cf1fa94dd4db03babb34a2" },
    [ordered]@{ Name = "Hand4Whole_RELEASE"; Url = "https://github.com/mks0601/Hand4Whole_RELEASE.git"; Commit = "c94908654b8108f241f18f04b4a493c05137edf6" },
    [ordered]@{ Name = "mmpose"; Url = "https://github.com/open-mmlab/mmpose.git"; Commit = "759b39c13fea6ba094afc1fa932f51dc1b11cbf9" },
    [ordered]@{ Name = "segment-anything"; Url = "https://github.com/facebookresearch/segment-anything.git"; Commit = "dca509fe793f601edb92606367a655c15ac00fdf" },
    [ordered]@{ Name = "Depth-Anything-V2"; Url = "https://github.com/DepthAnything/Depth-Anything-V2.git"; Commit = "a561b849ebae10a6f5ef49e26c83cbbcd36c71bf" },
    [ordered]@{ Name = "diff-gaussian-rasterization-depth"; Url = "https://github.com/leo-frank/diff-gaussian-rasterization-depth.git"; Commit = "03f0b7d00383d6e96c22b37325ac9e5450947bf5" }
)

function Invoke-WslRoot {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Capture
    )
    $prefix = @("-d", $Distribution, "-u", "root", "--")
    if ($Capture) {
        $output = @(& $WslExe @prefix @Arguments 2>&1)
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            throw "WSL command failed ($code): $($Arguments -join ' ')`n$($output -join [Environment]::NewLine)"
        }
        return ,$output
    }
    & $WslExe @prefix @Arguments
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "WSL command failed ($code): $($Arguments -join ' ')" }
}

if ([string]::IsNullOrWhiteSpace($Distribution)) { throw "Distribution is required." }
if ([string]::IsNullOrWhiteSpace($LinuxDependencyRoot) -or -not $LinuxDependencyRoot.StartsWith('/')) {
    throw "LinuxDependencyRoot must be an absolute Linux path."
}
if ($LinuxDependencyRoot -eq "/") { throw "LinuxDependencyRoot may not be '/'." }

Invoke-WslRoot -Arguments @("/usr/bin/env", "true")
$gitVersion = Invoke-WslRoot -Arguments @("/usr/bin/git", "--version") -Capture
Write-Host "Git: $([string]$gitVersion[0])"

$parent = $LinuxDependencyRoot.Substring(0, $LinuxDependencyRoot.LastIndexOf('/'))
if ([string]::IsNullOrWhiteSpace($parent)) { $parent = "/" }
$stage = "$parent/.bodyrig-exavatar-deps-stage-$([Guid]::NewGuid().ToString('N'))"

$existingCode = 1
& $WslExe -d $Distribution -u root -- /usr/bin/test -e $LinuxDependencyRoot
$existingCode = $LASTEXITCODE
if ($existingCode -eq 0 -and -not $Force) {
    throw "ExAvatar dependency root already exists: $LinuxDependencyRoot. Use -Force only to intentionally rebuild it."
}

Write-Host "============================================================"
Write-Host "BODYRIG EXAVATAR PUBLIC CODE SETUP"
Write-Host "Distribution:       $Distribution"
Write-Host "Dependency root:    $LinuxDependencyRoot"
Write-Host "Repository count:   $($repos.Count)"
Write-Host "Restricted assets:  NOT DOWNLOADED"
Write-Host "Production:         FALSE"
Write-Host "============================================================"

try {
    Invoke-WslRoot -Arguments @("/bin/mkdir", "-p", $parent)
    Invoke-WslRoot -Arguments @("/bin/mkdir", "-p", $stage)

    $receiptRepos = @()
    foreach ($repo in $repos) {
        $target = "$stage/$($repo.Name)"
        Write-Host ""
        Write-Host "Clone $($repo.Name) @ $($repo.Commit)"
        Invoke-WslRoot -Arguments @("/usr/bin/git", "clone", "--no-checkout", "--filter=blob:none", $repo.Url, $target)
        Invoke-WslRoot -Arguments @("/usr/bin/git", "-C", $target, "checkout", "--detach", $repo.Commit)
        Invoke-WslRoot -Arguments @("/usr/bin/git", "-C", $target, "submodule", "update", "--init", "--recursive")

        $headRaw = Invoke-WslRoot -Arguments @("/usr/bin/git", "-C", $target, "rev-parse", "HEAD") -Capture
        $head = ([string]$headRaw[0]).Trim().ToLowerInvariant()
        if ($head -ne $repo.Commit) { throw "Pinned commit mismatch for $($repo.Name): $head" }
        $statusRaw = Invoke-WslRoot -Arguments @("/usr/bin/git", "-C", $target, "status", "--porcelain") -Capture
        $status = ($statusRaw | ForEach-Object { [string]$_ }) -join "`n"
        if (-not [string]::IsNullOrWhiteSpace($status)) { throw "Fresh dependency checkout is dirty: $($repo.Name)" }

        $receiptRepos += [ordered]@{
            name = $repo.Name
            repository = $repo.Url
            commit = $head
            clean = $true
        }
    }

    $receipt = [ordered]@{
        format = "bodyrig-photoreal-exavatar-public-dependencies"
        version = 1
        repositories = $receiptRepos
        restricted_assets_downloaded = $false
        build_only = $true
        production_activation = $false
    }
    $receiptJson = $receipt | ConvertTo-Json -Depth 10 -Compress
    $receiptBytes = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($receiptJson + "`n"))
    Invoke-WslRoot -Arguments @(
        "/usr/bin/python3", "-c",
        "import base64,pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(base64.b64decode(sys.argv[2]))",
        "$stage/bodyrig-public-dependencies.json",
        $receiptBytes
    )

    if ($existingCode -eq 0) {
        if (-not $Force) { throw "Dependency root appeared during staging: $LinuxDependencyRoot" }
        Invoke-WslRoot -Arguments @("/bin/rm", "-rf", $LinuxDependencyRoot)
    }
    Invoke-WslRoot -Arguments @("/bin/mv", $stage, $LinuxDependencyRoot)

    Write-Host ""
    Write-Host "BodyRig ExAvatar public dependency root: READY"
    Write-Host "Root:              $LinuxDependencyRoot"
    Write-Host "Pinned repos:       $($repos.Count)"
    Write-Host "Restricted assets:  NOT DOWNLOADED"
    Write-Host "Production:         FALSE"
} finally {
    & $WslExe -d $Distribution -u root -- /bin/rm -rf $stage 2>$null
}
