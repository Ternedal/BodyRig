from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "bodyrig/automatic_activation_status.py",
    "from .acceptance_status import AcceptanceStatusError, _read_json, _validate_gate_a\n",
    "from .acceptance_status import AcceptanceStatusError, _read_json, _validate_gate_a, inspect_acceptance_dir\n",
)
replace_once(
    "bodyrig/automatic_activation_status.py",
    "from .automatic_release_gate import (\n",
    "from .renderer_human_rejection import any_rejection_exists\nfrom .automatic_release_gate import (\n",
)
activation_anchor = '''    gate_report = _read_json(gate_path, "Gate A acceptance")\n    if require_git_state:\n'''
activation_guard = '''    gate_report = _read_json(gate_path, "Gate A acceptance")\n    if any_rejection_exists(acceptance_dir):\n        try:\n            rejection_status = inspect_acceptance_dir(acceptance_dir)\n        except AcceptanceStatusError as exc:\n            raise AutomaticReleaseGateError(f"renderer human rejection is invalid: {exc}") from exc\n        if rejection_status.state != "blocked" or not rejection_status.gate.endswith("-rejected"):\n            raise AutomaticReleaseGateError("renderer human rejection exists without canonical blocked authority")\n        raise AutomaticReleaseGateError(\n            f"renderer human rejection blocks automatic production activation: {rejection_status.message}"\n        )\n    if require_git_state:\n'''
replace_once("bodyrig/automatic_activation_status.py", activation_anchor, activation_guard)

replace_once(
    "bodyrig/automatic_release_gate.py",
    "from .acceptance_status import AcceptanceStatusError, _read_json, _sha256, _validate_gate_a\n",
    "from .acceptance_status import AcceptanceStatusError, _read_json, _sha256, _validate_gate_a, inspect_acceptance_dir\n"
    "from .renderer_human_rejection import any_rejection_exists\n",
)
release_anchor = '''    gate_report = _read_json(gate_path, "Gate A acceptance")\n    if require_git_state:\n'''
release_guard = '''    gate_report = _read_json(gate_path, "Gate A acceptance")\n    if any_rejection_exists(acceptance_dir):\n        try:\n            rejection_status = inspect_acceptance_dir(acceptance_dir)\n        except AcceptanceStatusError as exc:\n            raise AutomaticReleaseGateError(f"renderer human rejection is invalid: {exc}") from exc\n        if rejection_status.state != "blocked" or not rejection_status.gate.endswith("-rejected"):\n            raise AutomaticReleaseGateError("renderer human rejection exists without canonical blocked authority")\n        raise AutomaticReleaseGateError(\n            f"renderer human rejection blocks automatic release: {rejection_status.message}"\n        )\n    if require_git_state:\n'''
replace_once("bodyrig/automatic_release_gate.py", release_anchor, release_guard)

test = Path("tests/test_automatic_production_activation.py")
text = test.read_text(encoding="utf-8")
import_anchor = '''from bodyrig.automatic_release_gate import (\n    AutomaticReleaseGateError,\n    QUALITY_THRESHOLDS,\n    validate_and_build,\n)\n'''
if text.count(import_anchor) != 1:
    raise SystemExit("automatic test import anchor mismatch")
text = text.replace(
    import_anchor,
    import_anchor + "from bodyrig.renderer_human_rejection import write_rejection\n",
    1,
)
addition = r'''


def reject_windows_fidelity(acceptance: Path) -> None:
    gate_path = acceptance / "bodyrig-acceptance.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    probe = acceptance / "windows-evidence" / "windows-probe.json"
    deformation = acceptance / "windows-evidence" / "windows-deformation-probe.json"
    write_rejection(
        acceptance,
        platform="windows-unity-univrm",
        bodyrig_revision=REVISION,
        body_id=BODY_ID,
        automated_report_sha256=sha(gate_path),
        probe_report_sha256=sha(probe),
        deformation_report_sha256=sha(deformation),
        package_sha256=str(gate["package"]["package_sha256"]),
        runtime_manifest_sha256=str(gate["runtime"]["manifest_sha256"]),
        failed_checks=["source_identity", "geometry_proportions", "skin_appearance"],
        quality_note="Human review rejected identity, proportions and skin fidelity.",
    )


def test_human_rejection_blocks_automatic_resume_and_release(tmp_path: Path) -> None:
    acceptance, repo = build_fixture(tmp_path)
    reject_windows_fidelity(acceptance)
    with pytest.raises(AutomaticReleaseGateError, match="human rejection blocks automatic production activation"):
        inspect_automatic_activation(acceptance, repo, require_git_state=False)
    with pytest.raises(AutomaticReleaseGateError, match="human rejection blocks automatic release"):
        validate_and_build(acceptance, repo, require_git_state=False)
'''
if "test_human_rejection_blocks_automatic_resume_and_release" in text:
    raise SystemExit("automatic rejection regression already exists")
test.write_text(text + addition, encoding="utf-8")
