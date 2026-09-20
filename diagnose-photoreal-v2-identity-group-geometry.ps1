param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$ReviewRoot,
    [string]$ModelRoot = "",
    [string]$DiagnosticRecognizerRoot = "",
    [switch]$AcceptInsightFaceResearchLicense,
    [switch]$OpenWitnessReview,
    [string]$Distribution = "Ubuntu-22.04",
    [string]$LinuxPython = "/opt/bodyrig-photoreal/bin/python",
    [ValidateSet("cpu", "cuda", "cuda:0")][string]$Device = "cuda:0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Need-File {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Need-Directory {
    param([string]$Path,[string]$Label)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Label not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Convert-ToWslPath {
    param([string]$WindowsPath)
    if ($WindowsPath.StartsWith('/')) { return $WindowsPath }

    $pythonCode = @'
import base64
import sys
sys.path.insert(0, sys.argv[1])
from bodyrig.wsl_adapter_bridge import make_wsl_path_converter
value = make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4])
print(base64.b64encode(value.encode("utf-8")).decode("ascii"))
'@
    $lines = @(& $script:WindowsPython -c $pythonCode $script:RepoRoot "wsl.exe" $Distribution $WindowsPath 2>&1)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -ne 1) {
        throw "Could not convert path with BodyRig WSL bridge: $WindowsPath | $($lines -join ' ')"
    }
    $encoded = ([string]$lines[0]).Trim()
    try {
        $value = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
    } catch {
        throw "BodyRig WSL bridge returned invalid encoded path data: $WindowsPath"
    }
    if ([string]::IsNullOrWhiteSpace($value) -or -not $value.StartsWith('/')) {
        throw "BodyRig WSL bridge returned invalid path: $WindowsPath"
    }
    return $value
}

function New-WslTransportRequest {
    param(
        [string]$SourceRequest,
        [string]$Prefix
    )
    $requestObject = Get-Content -LiteralPath $SourceRequest -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
    if ($null -eq $requestObject.sources -or @($requestObject.sources).Count -eq 0) {
        throw "$Prefix request contains no sources."
    }
    foreach ($source in @($requestObject.sources)) {
        $raw = ([string]$source.resolved_path).Trim()
        if ([string]::IsNullOrWhiteSpace($raw)) {
            throw "$Prefix source has no resolved_path."
        }
        $source.resolved_path = Convert-ToWslPath -WindowsPath $raw
    }
    $temp = Join-Path ([IO.Path]::GetTempPath()) (
        "bodyrig-{0}-{1}.json" -f $Prefix.ToLowerInvariant().Replace(" ", "-"), [Guid]::NewGuid().ToString("N")
    )
    $requestObject | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temp -Encoding UTF8
    return $temp
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required on Windows."
}
if ([string]::IsNullOrWhiteSpace($Distribution)) {
    throw "WSL distribution is required."
}
if ([string]::IsNullOrWhiteSpace($LinuxPython) -or -not $LinuxPython.StartsWith('/')) {
    throw "LinuxPython must be an absolute Linux path."
}

$script:RepoRoot = (Resolve-Path $PSScriptRoot).Path
$script:WindowsPython = Need-File (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") "BodyRig Windows Python"

$dirty = @(git -C $script:RepoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect BodyRig Git status."
}
if ($dirty.Count -ne 0) {
    throw "Identity group geometry diagnostic requires a clean BodyRig checkout."
}
$head = ([string](git -C $script:RepoRoot rev-parse HEAD)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve exact BodyRig Git HEAD."
}

$RunDirectory = Need-Directory $RunDirectory "Photoreal resumed run"
$ReviewRoot = Need-Directory $ReviewRoot "Identity group review root"
$bank = Need-File (Join-Path $RunDirectory "identity-bank.json") "Identity bank"
$identityRequest = Need-File (Join-Path $RunDirectory "identity-extractor\request.json") "Stage-7 identity request"
$calibrationRequest = Need-File (Join-Path $RunDirectory "identity-calibration-extractor\request.json") "Stage-13 calibration request"
$negativeObservations = Need-File (Join-Path $RunDirectory "identity-calibration-extractor\output\negative-observations.json") "Identity negative observations"
$attestation = Need-File (Join-Path $ReviewRoot "identity-group-attestation.json") "Identity group attestation"
$tool = Need-File (Join-Path $script:RepoRoot "tools\photoreal_identity_group_geometry_diagnostic.py") "Identity group geometry diagnostic"
$setup = Need-File (Join-Path $script:RepoRoot "setup-photoreal-v2-identity-recognizer-diagnostic.ps1") "Diagnostic recognizer setup"

if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
    $ModelRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\reference-models"
}
$ModelRoot = Need-Directory $ModelRoot "Photoreal reference model root"

if ([string]::IsNullOrWhiteSpace($DiagnosticRecognizerRoot)) {
    $DiagnosticRecognizerRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\diagnostic-recognizers\antelopev2"
}
$recognizer = Join-Path $DiagnosticRecognizerRoot "glintr100.onnx"
$recognizerProvenance = Join-Path $DiagnosticRecognizerRoot "source-provenance.json"
if (
    -not (Test-Path -LiteralPath $recognizer -PathType Leaf) -or
    -not (Test-Path -LiteralPath $recognizerProvenance -PathType Leaf)
) {
    if (-not $AcceptInsightFaceResearchLicense) {
        throw "Pinned antelopev2 diagnostic recognizer is not installed. Re-run with -AcceptInsightFaceResearchLicense after reviewing and accepting the InsightFace pretrained-model research license."
    }
    & $setup -DiagnosticRoot $DiagnosticRecognizerRoot -AcceptInsightFaceResearchLicense
    if ($LASTEXITCODE -ne 0) {
        throw "Diagnostic recognizer setup failed with exit code $LASTEXITCODE."
    }
}
$DiagnosticRecognizerRoot = Need-Directory $DiagnosticRecognizerRoot "Pinned antelopev2 diagnostic recognizer root"
$recognizer = Need-File (Join-Path $DiagnosticRecognizerRoot "glintr100.onnx") "Pinned antelopev2 glintr100 recognizer"
$recognizerProvenance = Need-File (Join-Path $DiagnosticRecognizerRoot "source-provenance.json") "Pinned antelopev2 recognizer provenance"

$tempIdentityRequest = $null
$tempCalibrationRequest = $null
try {
    $tempIdentityRequest = New-WslTransportRequest -SourceRequest $identityRequest -Prefix "identity-group-geometry"
    $tempCalibrationRequest = New-WslTransportRequest -SourceRequest $calibrationRequest -Prefix "calibration-group-geometry"

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $output = Join-Path $RunDirectory ("identity-group-geometry-diagnostic-{0}.json" -f $stamp)
    if (Test-Path -LiteralPath $output) {
        throw "Identity group geometry diagnostic output already exists: $output"
    }

    $wslRepo = Convert-ToWslPath $script:RepoRoot
    $wslTool = Convert-ToWslPath $tool
    $wslBank = Convert-ToWslPath $bank
    $wslIdentityRequest = Convert-ToWslPath $tempIdentityRequest
    $wslIdentityRequestOrigin = Convert-ToWslPath $identityRequest
    $wslCalibrationRequest = Convert-ToWslPath $tempCalibrationRequest
    $wslCalibrationRequestOrigin = Convert-ToWslPath $calibrationRequest
    $wslNegativeObservations = Convert-ToWslPath $negativeObservations
    $wslReview = Convert-ToWslPath $ReviewRoot
    $wslModelRoot = Convert-ToWslPath $ModelRoot
    $wslDiagnosticRecognizerRoot = Convert-ToWslPath $DiagnosticRecognizerRoot
    $wslOutput = Convert-ToWslPath $output

    Write-Host "============================================================"
    Write-Host "BODYRIG PHOTOREAL V2 - IDENTITY GROUP GEOMETRY DIAGNOSTIC"
    Write-Host "Revision:       $head"
    Write-Host "Run:            $RunDirectory"
    Write-Host "Review:         $ReviewRoot"
    Write-Host "Attestation:    $attestation"
    Write-Host "Device:         $Device"
    Write-Host "Recognizers:    w600k_r50 + antelopev2/glintr100"
    Write-Host "Evidence:       exact 27 positive + persisted negative frames"
    Write-Host "Geometry:       per-group cohesion, LGO, positive neighbors, negative overlap"
    Write-Host "Ablation:       exhaustive counterfactual removal of 0-3 positive groups"
    Write-Host "Boundary:       exact floor/ceiling witnesses + single-reference sensitivity"
    Write-Host "Review:         exact frame/aligned-crop witness sibling comparison"
    Write-Host "Fusion:         41-point w600k_r50 / glintr100 weighted embedding sweep"
    Write-Host "Consensus:      source-group top-k support sweep with all evidence retained"
    Write-Host "Source rehash:  NO"
    Write-Host "Authority:      DIAGNOSTIC ONLY / FALSE"
    Write-Host "Production:     FALSE"
    Write-Host "============================================================"
    Write-Host ""

    $wslArgs = @(
        "-d", $Distribution, "--", "env",
        "PYTHONPATH=$wslRepo",
        "BODYRIG_REVISION=$head",
        $LinuxPython, $wslTool,
        "--identity-bank", $wslBank,
        "--identity-request", $wslIdentityRequest,
        "--identity-request-origin", $wslIdentityRequestOrigin,
        "--calibration-request", $wslCalibrationRequest,
        "--calibration-request-origin", $wslCalibrationRequestOrigin,
        "--negative-observations", $wslNegativeObservations,
        "--review-root", $wslReview,
        "--model-root", $wslModelRoot,
        "--diagnostic-recognizer-root", $wslDiagnosticRecognizerRoot,
        "--device", $Device,
        "--out", $wslOutput
    )

    & wsl.exe @wslArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Identity group geometry diagnostic failed with exit code $LASTEXITCODE."
    }

    $result = Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100

    Write-Host ""
    Write-Host "Identity group geometry diagnostic: PASS"
    Write-Host "Positive references: $($result.positive_reference_count)"
    Write-Host "Human-attested groups: $($result.human_attested_group_count)"
    Write-Host "Persisted negatives: $($result.negative_observation_count)"
    Write-Host ""
    Write-Host "Per-group comparison (weakest alternate local separation first):"
    foreach ($row in @($result.group_comparison)) {
        Write-Host (
            "  {0,-12} refs={1,2} | w600k LGO={2,10} neg={3,10} margin={4,10} | glintr100 LGO={5,10} neg={6,10} margin={7,10} | delta={8,10}" -f
            $row.group_id,
            $row.reference_count,
            $row.current_centroid_lgo,
            $row.current_highest_negative_group_cosine,
            $row.current_local_group_separation_margin,
            $row.alternate_centroid_lgo,
            $row.alternate_highest_negative_group_cosine,
            $row.alternate_local_group_separation_margin,
            $row.delta_local_group_separation_margin
        )
    }
    Write-Host ""
    $currentPair = @($result.variants."w600k-r50".pairwise_positive_group_cosines)[0]
    $alternatePair = @($result.variants."antelopev2-glintr100".pairwise_positive_group_cosines)[0]
    Write-Host ("Weakest w600k positive pair:   {0} <-> {1} cosine={2}" -f $currentPair.left_group_id, $currentPair.right_group_id, $currentPair.cosine)
    Write-Host ("Weakest glintr100 positive pair:{0} <-> {1} cosine={2}" -f $alternatePair.left_group_id, $alternatePair.right_group_id, $alternatePair.cosine)
    Write-Host ""
    Write-Host "Counterfactual group ablation (diagnostic only):"
    foreach ($variantName in @("w600k-r50","antelopev2-glintr100")) {
        $ablation = $result.counterfactual_group_ablation.$variantName
        Write-Host ("  {0}" -f $variantName)
        foreach ($count in @("1","2","3")) {
            $best = @($ablation.by_removed_count.$count)[0]
            $currentScore = $best.scoring_models."current-reference-weighted".observed_separation_margin
            $balancedScore = $best.scoring_models."group-balanced-centroid-lgo".observed_separation_margin
            $prototypeScore = $best.scoring_models."nearest-group-prototype".observed_separation_margin
            Write-Host (
                "    remove {0}: groups=[{1}] refs={2} | current={3} balanced={4} prototype={5} all-pass={6}" -f
                $count,
                ($best.removed_group_ids -join ","),
                $best.removed_reference_count,
                $currentScore,
                $balancedScore,
                $prototypeScore,
                $best.all_models_meet_margin
            )
        }
        $candidate = $ablation.candidate_scene_805_889_978
        if ($null -ne $candidate) {
            Write-Host (
                "    candidate 805+889+978: current={0} balanced={1} prototype={2} all-pass={3}" -f
                $candidate.scoring_models."current-reference-weighted".observed_separation_margin,
                $candidate.scoring_models."group-balanced-centroid-lgo".observed_separation_margin,
                $candidate.scoring_models."nearest-group-prototype".observed_separation_margin,
                $candidate.all_models_meet_margin
            )
        }
        if ($null -ne $ablation.first_all_models_pass) {
            Write-Host (
                "    first all-model pass: remove=[{0}] refs={1}" -f
                ($ablation.first_all_models_pass.removed_group_ids -join ","),
                $ablation.first_all_models_pass.removed_reference_count
            )
        } else {
            Write-Host "    first all-model pass: NONE within 3 removed groups"
        }
    }

    Write-Host ""
    Write-Host "Boundary witness after counterfactual removal [scene:805,scene:889,scene:978]:"
    foreach ($variantName in @("w600k-r50","antelopev2-glintr100")) {
        $boundary = $result.candidate_boundary_witness.$variantName
        $currentWitness = $boundary.baseline_witnesses."current-reference-weighted"
        $floor = $currentWitness.positive_floor_witness
        $ceiling = $currentWitness.negative_ceiling_witness
        Write-Host (
            "  {0}: floor ref={1} group={2} score={3} | ceiling neg={4} subject={5} score={6} | margin={7}" -f
            $variantName,
            $floor.reference_index,
            $floor.group_id,
            $floor.score,
            $ceiling.negative_index,
            $ceiling.subject_performer_id,
            $ceiling.score,
            $currentWitness.observed_separation_margin
        )
        $bestRef = $boundary.best_single_reference_ablation
        if ($null -ne $bestRef) {
            Write-Host (
                "    best single-ref counterfactual: ref={0} group={1} min-margin={2} all-pass={3}" -f
                $bestRef.removed_reference_index,
                $bestRef.removed_group_id,
                $bestRef.minimum_margin_across_models,
                $bestRef.all_models_meet_margin
            )
            foreach ($modelName in @("current-reference-weighted","group-balanced-centroid-lgo","nearest-group-prototype")) {
                $score = $bestRef.scoring_models.$modelName
                Write-Host (
                    "      {0,-30} margin={1} meets={2}" -f
                    $modelName,
                    $score.observed_separation_margin,
                    $score.would_meet_margin
                )
            }
        }
        if ($null -ne $boundary.first_all_models_pass) {
            Write-Host (
                "    first single-ref all-model pass: ref={0} group={1}" -f
                $boundary.first_all_models_pass.removed_reference_index,
                $boundary.first_all_models_pass.removed_group_id
            )
        } else {
            Write-Host "    first single-ref all-model pass: NONE"
        }
    }

    Write-Host ""
    Write-Host "Source-group consensus sweep (all evidence retained):"
    foreach ($variantName in @("w600k-r50","antelopev2-glintr100")) {
        $consensus = $result.group_consensus_sweep.$variantName
        $best = $consensus.best_support
        Write-Host (
            "  {0}: best k={1} margin={2} meets={3} | floor ref={4} group={5} score={6} | ceiling neg={7} subject={8} score={9}" -f
            $variantName,
            $best.support_k,
            $best.observed_separation_margin,
            $best.would_meet_margin,
            $best.positive_floor_witness.reference_index,
            $best.positive_floor_witness.group_id,
            $best.positive_floor_witness.score,
            $best.negative_ceiling_witness.negative_index,
            $best.negative_ceiling_witness.subject_performer_id,
            $best.negative_ceiling_witness.score
        )
        if ($null -ne $consensus.first_passing_support) {
            $passing = $consensus.first_passing_support
            Write-Host (
                "    passing consensus exists: k={0} margin={1}" -f
                $passing.support_k,
                $passing.observed_separation_margin
            )
        } else {
            Write-Host "    passing consensus exists: NO"
        }
    }
    Write-Host ""
    Write-Host "Recognizer fusion sweep (all evidence retained):"
    $fusion = $result.recognizer_fusion_sweep
    $bestFusion = $fusion.best_weight
    Write-Host (
        "  best: w600k={0}% glintr100={1}% | min-margin={2} all-pass={3}" -f
        $bestFusion.current_percent,
        $bestFusion.alternate_percent,
        $bestFusion.minimum_margin_across_models,
        $bestFusion.all_models_meet_margin
    )
    foreach ($modelName in @("current-reference-weighted","group-balanced-centroid-lgo","nearest-group-prototype")) {
        $score = $bestFusion.scoring_models.$modelName
        Write-Host (
            "    {0,-30} margin={1} meets={2}" -f
            $modelName,
            $score.observed_separation_margin,
            $score.would_meet_margin
        )
    }
    if ($null -ne $fusion.first_all_models_pass) {
        $firstFusion = $fusion.first_all_models_pass
        Write-Host (
            "  all-model pass exists: w600k={0}% glintr100={1}% min-margin={2}" -f
            $firstFusion.current_percent,
            $firstFusion.alternate_percent,
            $firstFusion.minimum_margin_across_models
        )
    } else {
        Write-Host "  all-model pass exists: NO"
    }
    if ($fusion.negative_observation_count_below_production_minimum) {
        Write-Host "  production calibration still blocked: only 7 negatives (<8)."
    }
    $witnessReviewRoot = Join-Path ([IO.Path]::GetDirectoryName($output)) (([IO.Path]::GetFileNameWithoutExtension($output)) + "-witness-review")
    $witnessReviewHtml = Join-Path $witnessReviewRoot "review-index.html"
    $witnessReviewJson = Join-Path $witnessReviewRoot "boundary-witness-review.json"
    Write-Host ""
    Write-Host "Boundary witness visual review:"
    Write-Host "  HTML: $witnessReviewHtml"
    Write-Host "  JSON: $witnessReviewJson"
    if ($OpenWitnessReview) {
        if (-not (Test-Path -LiteralPath $witnessReviewHtml -PathType Leaf)) {
            throw "Boundary witness review HTML was not created: $witnessReviewHtml"
        }
        Start-Process $witnessReviewHtml
    } else {
        Write-Host "  Open with:"
        Write-Host $witnessReviewHtml
    }
    Write-Host ""
    Write-Host "Diagnostic JSON: $output"
    Write-Host "Authority: diagnostic-only; no identity matching, training, photoreal or production authority."
} finally {
    if ($null -ne $tempIdentityRequest) {
        Remove-Item -LiteralPath $tempIdentityRequest -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $tempCalibrationRequest) {
        Remove-Item -LiteralPath $tempCalibrationRequest -Force -ErrorAction SilentlyContinue
    }
}
