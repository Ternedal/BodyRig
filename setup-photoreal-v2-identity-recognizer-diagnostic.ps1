param(
    [string]$DiagnosticRoot = "",
    [switch]$AcceptInsightFaceResearchLicense,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$archiveUrl = "https://github.com/deepinsight/insightface/releases/download/model-zoo/antelopev2.zip"
$archiveSha = "8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5"
$recognizerFile = "glintr100.onnx"
$recognizerSha = "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf"

if (-not $AcceptInsightFaceResearchLicense) {
    throw "antelopev2 pretrained weights are non-commercial research assets. Re-run with -AcceptInsightFaceResearchLicense only after reviewing and accepting that model license."
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required on Windows."
}
if ([string]::IsNullOrWhiteSpace($DiagnosticRoot)) {
    $DiagnosticRoot = Join-Path $env:LOCALAPPDATA "BodyRig\photoreal-v2\diagnostic-recognizers\antelopev2"
}
$DiagnosticRoot = [IO.Path]::GetFullPath($DiagnosticRoot)

function Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Download-File {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Path
    )
    Write-Host "Download: $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Download did not create file: $Path"
    }
    if ((Get-Item -LiteralPath $Path).Length -lt 1) {
        throw "Downloaded file is empty: $Path"
    }
}

if (Test-Path -LiteralPath $DiagnosticRoot) {
    if (-not $Force) {
        $existingRecognizer = Join-Path $DiagnosticRoot $recognizerFile
        $existingProvenance = Join-Path $DiagnosticRoot "source-provenance.json"
        if (
            (Test-Path -LiteralPath $existingRecognizer -PathType Leaf) -and
            (Test-Path -LiteralPath $existingProvenance -PathType Leaf) -and
            ((Sha256 -Path $existingRecognizer) -eq $recognizerSha)
        ) {
            $existing = Get-Content -LiteralPath $existingProvenance -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
            if (
                $existing.format -eq "bodyrig-photoreal-diagnostic-recognizer-provenance" -and
                $existing.version -eq 1 -and
                $existing.package -eq "antelopev2" -and
                $existing.archive_sha256 -eq $archiveSha -and
                $existing.recognizer_sha256 -eq $recognizerSha -and
                $existing.license_operator_accepted -eq $true -and
                $existing.diagnostic_only -eq $true -and
                $existing.production_activation -eq $false
            ) {
                Write-Host "BodyRig diagnostic recognizer: READY"
                Write-Host "Root:        $DiagnosticRoot"
                Write-Host "Recognizer: antelopev2 / glintr100"
                Write-Host "Production: FALSE"
                exit 0
            }
        }
        throw "Diagnostic recognizer root already exists but is not the exact verified antelopev2 package: $DiagnosticRoot. Re-run with -Force only after reviewing the directory."
    }
}

$parent = Split-Path -Parent $DiagnosticRoot
if ([string]::IsNullOrWhiteSpace($parent)) {
    throw "Diagnostic recognizer parent is invalid: $DiagnosticRoot"
}
New-Item -ItemType Directory -Path $parent -Force | Out-Null

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("bodyrig-antelopev2-" + [Guid]::NewGuid().ToString("N"))
$stageRoot = Join-Path $tempRoot "stage"
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

try {
    $archive = Join-Path $tempRoot "antelopev2.zip"
    Download-File -Url $archiveUrl -Path $archive
    $observedArchiveSha = Sha256 -Path $archive
    if ($observedArchiveSha -ne $archiveSha) {
        throw "InsightFace antelopev2 archive SHA-256 mismatch: expected=$archiveSha observed=$observedArchiveSha"
    }

    $extract = Join-Path $tempRoot "extract"
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    $matches = @(Get-ChildItem -LiteralPath $extract -Filter $recognizerFile -File -Recurse)
    if ($matches.Count -ne 1) {
        throw "Verified antelopev2 archive must contain exactly one $recognizerFile; found $($matches.Count)."
    }

    $sourceRecognizer = $matches[0].FullName
    $observedRecognizerSha = Sha256 -Path $sourceRecognizer
    if ($observedRecognizerSha -ne $recognizerSha) {
        throw "InsightFace antelopev2 recognizer SHA-256 mismatch: expected=$recognizerSha observed=$observedRecognizerSha"
    }

    $targetRecognizer = Join-Path $stageRoot $recognizerFile
    Copy-Item -LiteralPath $sourceRecognizer -Destination $targetRecognizer -Force -ErrorAction Stop

    $provenance = [ordered]@{
        format = "bodyrig-photoreal-diagnostic-recognizer-provenance"
        version = 1
        package = "antelopev2"
        archive_url = $archiveUrl
        archive_sha256 = $observedArchiveSha
        recognizer_file = $recognizerFile
        recognizer_sha256 = $observedRecognizerSha
        recognition_architecture = "ResNet100"
        recognition_training_set = "Glint360K"
        embedding_dimension = 512
        input_size = 112
        preprocessing = "insightface-arcface-1"
        license_operator_accepted = $true
        diagnostic_only = $true
        identity_matching_authorized = $false
        teacher_training_authorized = $false
        photoreal_acceptance_authority = $false
        production_activation = $false
    }
    $provenancePath = Join-Path $stageRoot "source-provenance.json"
    $provenance | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $provenancePath -Encoding UTF8

    if ((Sha256 -Path $targetRecognizer) -ne $recognizerSha) {
        throw "Staged diagnostic recognizer SHA-256 changed unexpectedly."
    }

    if (Test-Path -LiteralPath $DiagnosticRoot) {
        if (-not $Force) {
            throw "Diagnostic recognizer root appeared during staging: $DiagnosticRoot"
        }
        Remove-Item -LiteralPath $DiagnosticRoot -Recurse -Force
    }
    Move-Item -LiteralPath $stageRoot -Destination $DiagnosticRoot -ErrorAction Stop

    Write-Host ""
    Write-Host "BodyRig diagnostic recognizer: READY"
    Write-Host "Root:        $DiagnosticRoot"
    Write-Host "Recognizer: antelopev2 / glintr100 (ResNet100@Glint360K)"
    Write-Host "Archive SHA: $archiveSha"
    Write-Host "Model SHA:   $recognizerSha"
    Write-Host "Authority:   DIAGNOSTIC ONLY / FALSE"
    Write-Host "Production:  FALSE"
} finally {
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
