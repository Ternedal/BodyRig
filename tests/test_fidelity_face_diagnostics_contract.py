from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigFidelitySnapshotCapture.cs"


def test_canonical_manifest_views_remain_v1_and_exact() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'private const int Version = 1;' in source
    assert 'new CameraPose("front-full"' in source
    assert 'new CameraPose("three-quarter-full"' in source
    assert 'new CameraPose("side-full"' in source
    assert 'new CameraPose("face-front"' in source
    assert 'var canonicalPoses = new[]' in source
    assert 'foreach (var pose in canonicalPoses)' in source
    assert 'entries.Add(new SnapshotEntry' in source


def test_face_and_eye_diagnostics_are_written_outside_manifest_entries() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'var diagnosticPoses = new List<CameraPose>' in source
    assert 'new CameraPose("face-zoom"' in source
    assert '"face-three-quarter"' in source
    assert '"eyes-closeup"' in source
    assert 'HumanBodyBones.LeftEye' in source
    assert 'HumanBodyBones.RightEye' in source
    assert 'foreach (var pose in diagnosticPoses)' in source
    diagnostic_loop = source.split('foreach (var pose in diagnosticPoses)', 1)[1].split('}', 2)[0]
    assert 'WriteSnapshot(root, pose.Name, bytes);' in diagnostic_loop
    assert 'entries.Add' not in diagnostic_loop


def test_face_diagnostics_use_tighter_fixed_fov_without_changing_acceptance_semantics() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'faceZoomDistance = Mathf.Max(height * 0.19f, 0.24f)' in source
    assert 'faceTarget, 20f)' in source
    assert 'faceDistance * 0.62f' in source
    assert 'faceDistance * 0.78f' in source
    assert 'public string semantics = "visual-fidelity-not-identity-verification";' in source
