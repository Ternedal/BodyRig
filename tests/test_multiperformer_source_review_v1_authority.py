from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_PATH = ROOT / "discover-photoidentity-multiperformer-sources.ps1"
TRACK_PATH = ROOT / "prepare-photoidentity-multiperformer-track-review.ps1"
CROP_PATH = ROOT / "enrich-photoidentity-multiperformer-target-crops.ps1"
DISCOVERY = DISCOVERY_PATH.read_text(encoding="utf-8")
TRACK = TRACK_PATH.read_text(encoding="utf-8")
CROP = CROP_PATH.read_text(encoding="utf-8")


def _assert_v1_helper(source: str) -> None:
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source


def test_discovery_validates_stash_v1_before_credentials_and_source_scan() -> None:
    _assert_v1_helper(DISCOVERY)
    assert "Test-V1Version $stash.version" in DISCOVERY
    assert "[int]$stash.version" not in DISCOVERY

    guard = DISCOVERY.index("Test-V1Version $stash.version")
    decrypt = DISCOVERY.index("ConvertTo-SecureString", guard)
    path_map = DISCOVERY.index("$pathMap -PerformerId", decrypt)
    scan = DISCOVERY.index("bodyrig.photoidentity_multiperformer_source_discovery", path_map)
    assert guard < decrypt < path_map < scan

    for boundary in (
        "Persistent storage authentication is not QUALIFIED",
        "ZeroFreeBSTR",
        'SetEnvironmentVariable("STASH_URL", $oldUrl, "Process")',
        'SetEnvironmentVariable("STASH_API_KEY", $oldKey, "Process")',
        "Multi-performer discovery output must be outside the BodyRig Git checkout",
        "Machine target: FALSE",
        "Biometric ID:   FALSE",
        "Reconstruction: FALSE",
    ):
        assert boundary in DISCOVERY


def test_track_review_validates_discovery_v1_before_human_review_preparation() -> None:
    _assert_v1_helper(TRACK)
    assert "Test-V1Version $discovery.version" in TRACK
    assert "[int]$discovery.version" not in TRACK

    guard = TRACK.index("Test-V1Version $discovery.version")
    revision = TRACK.index("$discovery.bodyrig_revision -ne $head", guard)
    exhaustion = TRACK.index("$discovery.stash_inventory_exhausted -ne $true", revision)
    candidate = TRACK.index("$discovery.candidates | Where-Object", exhaustion)
    prepare = TRACK.index("bodyrig.photoidentity_multiperformer_review_prepare", candidate)
    assert guard < revision < exhaustion < candidate < prepare

    for boundary in (
        "PHALP target:     NONE (human decision required)",
        "Only after visually confirming the requested performer",
        "Machine identity selection: FALSE",
        "Biometric identity inference: FALSE",
        "Target-isolated source authority: FALSE",
        "Reconstruction permitted: FALSE",
    ):
        assert boundary in TRACK


def test_target_crop_validates_fitter_v1_before_runtime_and_enrichment() -> None:
    _assert_v1_helper(CROP)
    assert "Test-V1Version $fitter.version" in CROP
    assert "[int]$fitter.version" not in CROP

    guard = CROP.index("Test-V1Version $fitter.version")
    command = CROP.index("$command=@($fitter.command)", guard)
    preflight = CROP.index("bodyrig.sith_preflight", command)
    enrich = CROP.index("bodyrig.photoidentity_target_crop_enrich", preflight)
    assert guard < command < preflight < enrich

    for boundary in (
        'photoidentity-multiperformer-target-isolation-attestation.json',
        '"sith-smplx-vrm"',
        '"/build/examples/openpose/openpose.bin"',
        "Authority: machine observability candidates only",
        "Anatomy/rear/nails authority: NONE",
        "$result.source_detail_quality_authority -ne $false",
        "$result.photoidentity_source_evidence_authority -ne $false",
        "$result.reconstruction_permitted -ne $false",
        "$result.production_activation -ne $false",
    ):
        assert boundary in CROP


def _helper_source(source: str) -> str:
    start = source.index("function Test-V1Version($Value)")
    open_brace = source.index("{", start)
    depth = 0
    for index in range(open_brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("Test-V1Version function is unterminated")


@pytest.mark.parametrize("source", [DISCOVERY, TRACK, CROP])
@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is not installed")
def test_multiperformer_v1_helpers_reject_coercive_values(source: str) -> None:
    script = _helper_source(source) + r'''
$values = ConvertFrom-Json -InputObject '[1,1.0,true,false,"1",null,2]'
$results = @()
foreach ($value in @($values)) { $results += [bool](Test-V1Version $value) }
$results | ConvertTo-Json -Compress
'''
    completed = subprocess.run(
        ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip()) == [True, True, False, False, False, False, False]
