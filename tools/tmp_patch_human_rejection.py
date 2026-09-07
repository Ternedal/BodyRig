from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, found {count}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "bodyrig/renderer_human_rejection.py",
    '    return any((root / f"bodyrig-renderer-rejection-{prefix}.json").exists() for prefix in PLATFORMS.values())\n',
    '    return any(\n'
    '        candidate.exists() or candidate.is_symlink()\n'
    '        for prefix in PLATFORMS.values()\n'
    '        for candidate in (root / f"bodyrig-renderer-rejection-{prefix}.json",)\n'
    '    )\n',
)

replace_once(
    "bodyrig/acceptance_status.py",
    "from typing import Any\n\nSHA40 = re.compile",
    "from typing import Any\n\n"
    "from .renderer_human_rejection import (\n"
    "    RendererHumanRejectionError,\n"
    "    read_rejection,\n"
    "    rejection_path,\n"
    ")\n\n"
    "SHA40 = re.compile",
)

helper = '''

def _renderer_rejection_status(
    acceptance_dir: Path,
    *,
    platform: str,
    prefix: str,
    gate: GateAInfo,
) -> AcceptanceStatus | None:
    path = rejection_path(acceptance_dir, platform)
    if not (path.exists() or path.is_symlink()):
        return None
    attestation_name = (
        "bodyrig-renderer-acceptance-windows.json"
        if prefix == "windows"
        else "bodyrig-renderer-acceptance-quest.json"
    )
    paths = _platform_paths(acceptance_dir, prefix, attestation_name)
    if not paths.probe.is_file() or not paths.deformation.is_file():
        raise AcceptanceStatusError(
            f"{prefix} human rejection exists without the complete canonical machine/deformation evidence pair."
        )
    probe = _validate_probe(paths.probe, platform=platform, gate=gate)
    _validate_deformation(paths.deformation, platform=platform, probe=probe, gate=gate)
    try:
        rejection = read_rejection(
            acceptance_dir,
            platform=platform,
            bodyrig_revision=gate.revision,
            body_id=gate.body_id,
            automated_report_sha256=_sha256(gate.path),
            probe_report_sha256=_sha256(paths.probe),
            deformation_report_sha256=_sha256(paths.deformation),
            package_sha256=gate.package_hash,
            runtime_manifest_sha256=gate.runtime_hash,
        )
    except RendererHumanRejectionError as exc:
        raise AcceptanceStatusError(f"{prefix} human rejection is invalid: {exc}") from exc
    failures = ", ".join(str(item) for item in rejection["failed_checks"])
    note = str(rejection["quality_note"])
    return AcceptanceStatus(
        "blocked",
        f"{prefix}-rejected",
        str(acceptance_dir),
        gate.body_id,
        gate.revision,
        f"{prefix.capitalize()} human visual review rejected this exact acceptance. Failed checks: {failures}. Note: {note}",
        None,
    )
'''
replace_once(
    "bodyrig/acceptance_status.py",
    "\ndef _validate_attestation(path: Path, *, platform: str, gate: GateAInfo, paths: PlatformPaths) -> None:\n",
    helper + "\ndef _validate_attestation(path: Path, *, platform: str, gate: GateAInfo, paths: PlatformPaths) -> None:\n",
)

replace_once(
    "bodyrig/acceptance_status.py",
    '    gate_a_path = acceptance_dir / "bodyrig-acceptance.json"\n'
    '    gate = _validate_gate_a(gate_a_path)\n\n'
    '    windows_stage, windows = _platform_stage(\n',
    '    gate_a_path = acceptance_dir / "bodyrig-acceptance.json"\n'
    '    gate = _validate_gate_a(gate_a_path)\n\n'
    '    for platform, prefix in (\n'
    '        ("windows-unity-univrm", "windows"),\n'
    '        ("android-quest-class", "quest"),\n'
    '    ):\n'
    '        rejection = _renderer_rejection_status(\n'
    '            acceptance_dir, platform=platform, prefix=prefix, gate=gate\n'
    '        )\n'
    '        if rejection is not None:\n'
    '            return rejection\n\n'
    '    windows_stage, windows = _platform_stage(\n',
)

replace_once(
    "bodyrig/rig_window_acceptance.py",
    "from .automatic_release_gate import AutomaticReleaseGateError\n",
    "from .automatic_release_gate import AutomaticReleaseGateError\n"
    "from .renderer_human_rejection import any_rejection_exists\n",
)

replace_once(
    "bodyrig/rig_window_acceptance.py",
    'def inspect_for_rig_window(path: str | Path) -> dict[str, Any]:\n'
    '    acceptance_dir = Path(path).expanduser().resolve()\n'
    '    if has_automatic_evidence(acceptance_dir):\n',
    'def inspect_for_rig_window(path: str | Path) -> dict[str, Any]:\n'
    '    acceptance_dir = Path(path).expanduser().resolve()\n'
    '    if any_rejection_exists(acceptance_dir):\n'
    '        status = inspect_acceptance_dir(acceptance_dir)\n'
    '        payload = asdict(status)\n'
    '        payload["progress_rank"] = progress_rank(status)\n'
    '        payload["read_only"] = True\n'
    '        payload["policy_scope"] = "evidence-revision-structural"\n'
    '        return payload\n'
    '    if has_automatic_evidence(acceptance_dir):\n',
)

path = Path("tests/test_acceptance_status.py")
text = path.read_text(encoding="utf-8")
import_anchor = "from bodyrig.acceptance_status import AcceptanceStatusError, _session_status, inspect_acceptance_dir\n"
if text.count(import_anchor) != 1:
    raise SystemExit("tests/test_acceptance_status.py import anchor mismatch")
text = text.replace(
    import_anchor,
    import_anchor
    + "from bodyrig.renderer_human_rejection import write_rejection\n"
    + "from bodyrig.rig_window_acceptance import inspect_for_rig_window\n",
    1,
)
addition = r'''


def reject_renderer(
    fixture: GateFixture,
    prefix: str,
    platform: str,
    *,
    failed_checks: list[str] | None = None,
) -> Path:
    probe_path = evidence_path(fixture, prefix, f"{prefix}-probe.json")
    deformation_path = evidence_path(fixture, prefix, f"{prefix}-deformation-probe.json")
    receipt = write_rejection(
        fixture.directory,
        platform=platform,
        bodyrig_revision=REVISION,
        body_id=BODY_ID,
        automated_report_sha256=sha(fixture.gate_path),
        probe_report_sha256=sha(probe_path),
        deformation_report_sha256=sha(deformation_path),
        package_sha256=fixture.package_hash,
        runtime_manifest_sha256=fixture.runtime_hash,
        failed_checks=failed_checks or ["source_identity", "skin_appearance"],
        quality_note="Human visual review rejected the exact rendered body fidelity.",
    )
    return Path(str(receipt["rejection_path"]))


def test_windows_human_rejection_blocks_acceptance_and_reuse(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    reject_renderer(
        fixture,
        "windows",
        "windows-unity-univrm",
        failed_checks=[
            "source_identity",
            "geometry_proportions",
            "skin_appearance",
            "hair_appearance",
            "eye_appearance",
            "face_secondary",
            "small_anatomical_detail",
        ],
    )

    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "blocked"
    assert status.gate == "windows-rejected"
    assert status.next_command is None
    assert "source_identity" in status.message

    structural = inspect_for_rig_window(tmp_path)
    assert structural["state"] == "blocked"
    assert structural["gate"] == "windows-rejected"
    assert structural["progress_rank"] == 0


def test_human_rejection_dominates_existing_attestation(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    complete_windows(fixture)
    reject_renderer(fixture, "windows", "windows-unity-univrm")
    status = inspect_acceptance_dir(tmp_path)
    assert status.state == "blocked"
    assert status.gate == "windows-rejected"


def test_human_rejection_dominates_automatic_evidence_detection(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    reject_renderer(fixture, "windows", "windows-unity-univrm")
    write_json(tmp_path / "windows-evidence" / "windows-deformation-quality.json", {"placeholder": True})
    structural = inspect_for_rig_window(tmp_path)
    assert structural["state"] == "blocked"
    assert structural["progress_rank"] == 0


def test_tampered_human_rejection_fails_closed(tmp_path: Path) -> None:
    fixture = gate_a(tmp_path)
    probe(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    deformation(fixture, "windows", "windows-unity-univrm", "WindowsPlayer", "Windows test rig")
    path = reject_renderer(fixture, "windows", "windows-unity-univrm")
    value = json.loads(path.read_text(encoding="utf-8"))
    value["probe_report_sha256"] = "9" * 64
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(AcceptanceStatusError, match="human rejection is invalid"):
        inspect_acceptance_dir(tmp_path)
'''
if "test_windows_human_rejection_blocks_acceptance_and_reuse" in text:
    raise SystemExit("rejection integration tests already present")
path.write_text(text + addition, encoding="utf-8")
