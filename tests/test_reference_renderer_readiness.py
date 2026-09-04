import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_reference_renderer_readiness_is_read_only_and_checks_full_toolchain() -> None:
    script = (REPO / "check-reference-renderer-ready.ps1").read_text(encoding="utf-8")

    for token in (
        "PowerShell 7+ (pwsh)",
        "reference-renderer\\renderer-contract.json",
        "ProjectSettings\\ProjectVersion.txt",
        "PlaybackEngines\\AndroidPlayer",
        '"SDK"',
        '"NDK"',
        '"OpenJDK"',
        "platform-tools\\adb.exe",
        "Get-Command git",
        "com.unity.mathematics",
        "com.unity.test-framework",
        "com.unity.timeline",
        "com.vrmc.gltf",
        "com.vrmc.vrm",
        "BodyRig reference renderer toolchain: READY",
        "No Unity project was opened and no physical evidence was created.",
    ):
        assert token in script

    assert "Unity.exe -batchmode" not in script
    assert "bodyrig.physical_session" not in script
    assert "clone-body-from-stash-ready.ps1" not in script
    assert script.rstrip().endswith("return")


def test_reference_renderer_readiness_registry_pins_match_manifest_and_build_contract() -> None:
    manifest = json.loads(
        (REPO / "reference-renderer" / "Packages" / "manifest.json").read_text(encoding="utf-8")
    )
    readiness = (REPO / "check-reference-renderer-ready.ps1").read_text(encoding="utf-8")
    build = (REPO / "reference-renderer" / "build-reference-renderer.ps1").read_text(encoding="utf-8")
    readme = (REPO / "reference-renderer" / "README.md").read_text(encoding="utf-8")

    for package in (
        "com.unity.mathematics",
        "com.unity.test-framework",
        "com.unity.timeline",
    ):
        version = manifest["dependencies"][package]
        assert f'"{package}" = "{version}"' in readiness
        assert f'"{package}" = "{version}"' in build
        assert f"`{package}` **{version}**" in readme


def test_first_physical_run_doctor_requires_renderer_toolchain_before_rig_readiness() -> None:
    doctor = (REPO / "prepare-first-physical-run.ps1").read_text(encoding="utf-8")

    renderer_check = doctor.index("& $rendererReadinessScript")
    rig_check = doctor.index("& $powerShellExe @readinessArgs")
    ready = doctor.index('Write-Host "BodyRig pre-session doctor: READY"')
    assert renderer_check < rig_check < ready
    assert '"check-reference-renderer-ready.ps1"' in doctor
    assert "reference-renderer toolchain readiness failed" in doctor
    assert "Recovery, selected-source decode, Stash, Unity and Quest build toolchains are ready." in doctor
