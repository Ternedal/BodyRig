from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSON_UTILITY = ROOT / "reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs"
LOADER = ROOT / "reference-renderer/Assets/BodyRig/BodyRigP3QuestReviewLoader.cs"
PROBE = ROOT / "reference-renderer/Assets/BodyRig/BodyRigP3QuestReviewProbe.cs"
BOOTSTRAP = ROOT / "reference-renderer/Assets/BodyRig/BodyRigP3QuestReviewBootstrap.cs"
PHYSICAL_BOOTSTRAP = ROOT / "reference-renderer/Assets/BodyRig/BodyRigPhysicalProbeBootstrap.cs"
AUTO_QUALITY = ROOT / "reference-renderer/Assets/BodyRig/BodyRigAutomaticDeformationQuality.cs"
BUILD = ROOT / "reference-renderer/Assets/BodyRig/Editor/BodyRigReferenceBuild.cs"
PACKAGES = ROOT / "reference-renderer/Packages/manifest.json"
BUILD_PS = ROOT / "reference-renderer/build-reference-renderer.ps1"
PREPARE = ROOT / "prepare-photoreal-v2-p3-quest2-review-runtime.ps1"
RUN = ROOT / "run-photoreal-v2-p3-quest2-review-probe.ps1"


def test_review_loader_has_separate_manifest_and_no_gate_a_inputs() -> None:
    source = LOADER.read_text(encoding="utf-8")
    assert "p3-quest2-review-manifest.json" in source
    assert "bodyrig-photoreal-p3-quest2-review-runtime-manifest" in source
    assert "avatar.vrm" in source
    assert "basecolor.png" in source
    assert "quest2-modular-provenance.json" in source
    assert "runtime-manifest.json" not in source
    assert "bodyprint.json" not in source
    assert ".mrbody" not in source


def test_review_manifest_is_raw_strict_read_in_unity() -> None:
    source = JSON_UTILITY.read_text(encoding="utf-8")
    assert "ValidateP3QuestReviewManifestJson" in source
    assert "P3QuestReviewManifestFields" in source
    assert 'raw != "true"' in source
    assert 'raw != "false"' in source
    assert "specialized-eye-component" in source
    assert "teacher-derived-hair-component" in source


def test_review_probe_requires_real_quest_but_refuses_xr_claims() -> None:
    source = PROBE.read_text(encoding="utf-8")
    assert "RuntimePlatform.Android" in source
    assert '"Quest"' in source
    assert '"Oculus"' in source
    assert "physical_device_observed = true" in source
    assert "xr_runtime_present = false" in source
    assert "stereo_rendering_observed = false" in source
    assert "vr_safe_frame_pacing_observed = false" in source
    assert "physical_runtime_review_complete = false" in source
    assert "runtime_acceptance_authority = false" in source
    assert "photoreal_acceptance_authority = false" in source
    assert "production_activation = false" in source


def test_review_probe_requires_materialized_eye_and_hair_visibility() -> None:
    source = PROBE.read_text(encoding="utf-8")
    assert "BodyRigP3QuestEyeComponent" in source
    assert "BodyRigP3QuestTeacherHair" in source
    assert "specialized_eye_component_visible" in source
    assert "teacher_hair_component_visible" in source
    assert "has no drawable renderer" in source


def test_review_app_is_isolated_from_gate_a_application() -> None:
    review = BOOTSTRAP.read_text(encoding="utf-8")
    physical = PHYSICAL_BOOTSTRAP.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")

    assert 'ReviewApplicationId =\n            "dk.ternedal.bodyrig.p3review"' in review
    assert "BodyRigP3QuestReviewBootstrap.ReviewApplicationId" in physical
    assert "return;" in physical
    assert 'P3ReviewApplicationId =\n            "dk.ternedal.bodyrig.p3review"' in build
    assert "BuildP3QuestReviewBatch" in build
    assert "BodyRigP3QuestReview.apk" in build



def test_production_auto_components_are_disabled_in_review_app() -> None:
    physical = PHYSICAL_BOOTSTRAP.read_text(encoding="utf-8")
    automatic = AUTO_QUALITY.read_text(encoding="utf-8")
    marker = "BodyRigP3QuestReviewBootstrap.ReviewApplicationId"
    assert marker in physical
    assert marker in automatic


def test_review_probe_does_not_pretend_current_project_has_xr() -> None:
    packages = PACKAGES.read_text(encoding="utf-8").lower()
    probe = PROBE.read_text(encoding="utf-8")
    assert "openxr" not in packages
    assert "oculus" not in packages
    assert "xr_runtime_present = false" in probe
    assert "stereo_rendering_observed = false" in probe
    assert "vr_safe_frame_pacing_observed = false" in probe


def test_build_wrapper_exposes_only_explicit_p3_review_target() -> None:
    source = BUILD_PS.read_text(encoding="utf-8")
    assert 'ValidateSet("Windows", "Quest", "P3QuestReview")' in source
    assert "BuildP3QuestReviewBatch" in source
    assert "BodyRigP3QuestReview.apk" in source


def test_review_operators_never_claim_xr_or_acceptance() -> None:
    prepare = PREPARE.read_text(encoding="utf-8")
    run = RUN.read_text(encoding="utf-8")

    assert "Gate A / BodyPrint:    NOT USED" in prepare
    assert "XR/stereo acceptance:  FALSE" in prepare
    assert "Production:            FALSE" in prepare

    assert "P3QuestReview" in run
    assert "dk.ternedal.bodyrig.p3review" in run
    assert "xr_runtime_present" in run
    assert "stereo_rendering_observed" in run
    assert "vr_safe_frame_pacing_observed" in run
    assert "Photoreal acceptance:   FALSE" in run
    assert "Production:             FALSE" in run


def test_review_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    for script in (PREPARE, RUN, BUILD_PS):
        command = (
            "$tokens=$null; $errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{script.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
