from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HAIR_PROBE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigHairDeformationProbe.cs"
BOOTSTRAP = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs"
FIDELITY_WRAPPER = ROOT / "run-fidelity-windows-render-probe.ps1"
PREVIEW_WRAPPER = ROOT / "run-source-hair-eye-windows-preview.ps1"
SCHEMA = ROOT / "contracts" / "bodyrig-hair-deformation-probe-v1.schema.json"


def test_hair_probe_uses_real_head_bone_and_baked_skinned_mesh_motion() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    for marker in (
        'HairNodeName = "BodyRigSourceHairReview"',
        'HairMeshName = "BodyRigSourceHairReviewMesh"',
        'SequenceRevision = "source-hair-head-turn-v1"',
        'HeadTurnDegrees = 28.0f',
        'HumanBodyBones.Head',
        'SkinnedMeshRenderer',
        'renderer.BakeMesh(mesh)',
        'head.localRotation = baselineRotation * Quaternion.Euler(0f, HeadTurnDegrees, 0f)',
        'head.localRotation = baselineRotation',
        'vertex_motion_observed = true',
        'restored_neutral = true',
        'human_review_required = true',
        'comparison_only = true',
        'hair_component_authority = false',
        'production_activation = false',
    ):
        assert marker in source

    assert 'MinimumMotionRmsMeters = 0.00025f' in source
    assert 'MinimumMotionMaxMeters = 0.001f' in source
    assert 'MaximumRestorationRmsMeters = 0.00025f' in source
    assert 'MaximumRestorationMaxMeters = 0.001f' in source


def test_physical_bootstrap_runs_hair_probe_only_when_explicit_output_is_requested() -> None:
    source = BOOTSTRAP.read_text(encoding="utf-8")

    assert 'HairDeformationOutputArg = "--bodyrig-hair-deformation-output"' in source
    assert 'var hairDeformationPath = GetArgument(HairDeformationOutputArg);' in source
    assert 'if (!string.IsNullOrWhiteSpace(hairDeformationPath))' in source
    assert 'gameObject.AddComponent<BodyRigHairDeformationProbe>()' in source
    assert 'hairProbe.RunProbeAsync(hairDeformationPath' in source
    assert 'Machine evidence only; inspect hair attachment, clipping and silhouette visually.' in source


def test_fidelity_review_mode_hash_binds_hair_probe_without_changing_normal_modes() -> None:
    source = FIDELITY_WRAPPER.read_text(encoding="utf-8")

    assert 'if ($usingReviewRuntime) {' in source
    assert '$args += @("--bodyrig-hair-deformation-output", $hairDeformationPath)' in source
    assert 'Read-Json $hairDeformationPath "Source hair deformation probe"' in source
    assert 'hair_deformation_probe_sha256' in source
    assert 'hair_deformation_machine_pass = $true' in source
    assert 'hair_deformation_human_review_required = $true' in source
    assert 'hair_component_authority -ne $false' in source
    assert 'production_activation -ne $false' in source
    assert '[double]$hairDeformation.vertex_motion_rms_m -lt 0.00025' in source
    assert '[double]$hairDeformation.vertex_motion_max_m -lt 0.001' in source
    assert '[double]$hairDeformation.restoration_rms_m -gt 0.00025' in source
    assert '[double]$hairDeformation.restoration_max_m -gt 0.001' in source


def test_single_hair_eye_preview_command_requires_exact_hair_motion_evidence_before_ready() -> None:
    source = PREVIEW_WRAPPER.read_text(encoding="utf-8")

    ready = source.index('BodyRig source hair + eye Windows preview: READY')
    probe_need = source.index('hair-deformation-probe.json')
    probe_hash = source.index('hair_deformation_probe_sha256')
    machine_pass = source.index('hair_deformation_machine_pass -ne $true')
    threshold = source.index('vertex_motion_rms_m -lt 0.00025')
    assert probe_need < ready
    assert probe_hash < ready
    assert machine_pass < ready
    assert threshold < ready
    assert 'Hair move:   MACHINE PASS; human clipping/attachment review still required' in source
    assert 'hair_component_authority -ne $false' in source
    assert 'production_activation -ne $false' in source


def test_hair_deformation_schema_is_strict_review_only_machine_evidence() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert schema["additionalProperties"] is False
    required = set(schema["required"])
    assert {
        "package_sha256",
        "runtime_manifest_sha256",
        "avatar_sha256",
        "bodyprint_sha256",
        "head_bone_bound",
        "vertex_motion_rms_m",
        "vertex_motion_max_m",
        "restoration_rms_m",
        "restoration_max_m",
        "human_review_required",
        "hair_component_authority",
        "production_activation",
    } <= required
    props = schema["properties"]
    assert props["format"]["const"] == "bodyrig-hair-deformation-probe"
    assert props["sequence_revision"]["const"] == "source-hair-head-turn-v1"
    assert props["hair_node"]["const"] == "BodyRigSourceHairReview"
    assert props["hair_mesh"]["const"] == "BodyRigSourceHairReviewMesh"
    assert props["head_bone_bound"]["const"] is True
    assert props["vertex_motion_observed"]["const"] is True
    assert props["restored_neutral"]["const"] is True
    assert props["human_review_required"]["const"] is True
    assert props["comparison_only"]["const"] is True
    assert props["hair_component_authority"]["const"] is False
    assert props["production_activation"]["const"] is False
