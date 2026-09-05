from pathlib import Path


def test_avatar_loader_sha_guard_has_balanced_condition() -> None:
    source = Path("reference-renderer/Assets/BodyRig/BodyRigAvatarLoader.cs").read_text(encoding="utf-8")

    assert "if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')))" in source
    assert "if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f'))\n" not in source


def test_renderer_build_waits_for_unity_and_uses_real_exit_code() -> None:
    script = Path("reference-renderer/build-reference-renderer.ps1").read_text(encoding="utf-8")

    assert "function Invoke-UnityBatch" in script
    assert "[System.Diagnostics.ProcessStartInfo]::new()" in script
    assert ".ArgumentList.Add" in script
    assert "$process.WaitForExit()" in script
    assert "$process.ExitCode" in script
    assert "$exitCode = Invoke-UnityBatch" in script
    assert "& $UnityExe -batchmode" not in script


def test_renderer_build_fails_closed_on_project_and_contract_drift_before_unity() -> None:
    script = Path("reference-renderer/build-reference-renderer.ps1").read_text(encoding="utf-8")

    project_check = script.index("ProjectSettings\\ProjectVersion.txt")
    resolve_unity = script.index("$UnityExe = Resolve-UnityEditor")
    assert project_check < resolve_unity
    assert "Reference renderer project version does not match renderer-contract Unity version" in script
    assert 'contract.application_id -ne "dk.ternedal.bodyrig.reference"' in script
    assert 'contract.deformation_sequence_revision -ne "humanoid-muscle-sweep-v1"' in script
    assert "Unity package manifest does not pin both UniVRM packages" in script
