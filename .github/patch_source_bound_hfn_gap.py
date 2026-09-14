from pathlib import Path

root = Path(__file__).resolve().parents[1]
module_path = root / "bodyrig" / "fidelity_component_gap_executor.py"
test_path = root / "tests" / "test_fidelity_component_gap_executor.py"
module = module_path.read_text(encoding="utf-8")
test = test_path.read_text(encoding="utf-8")

# Imports for package appearance authority + canonical HFN continuation.
module = module.replace(
    "import subprocess\nimport sys\n",
    "import subprocess\nimport sys\nimport zipfile\n",
    1,
)
anchor = "from .fidelity_component_gap import SEMANTICS as GAP_SEMANTICS\n"
insert = '''from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .high_fidelity_face_secondary_runtime import APPEARANCE_METHOD
from .high_fidelity_hfn_continuation import (
    CANDIDATE_GATE as HFN_CANDIDATE_GATE,
    HUMAN_GATE as HFN_HUMAN_GATE,
    RENDER_GATE as HFN_RENDER_GATE,
    inspect_hfn_continuation,
)
from .package import MRBodyError, validate_package
'''
if module.count(anchor) != 1:
    raise SystemExit("executor import anchor drifted")
module = module.replace(anchor, anchor + insert, 1)

anchor = 'FACE_MACHINE_GATES = {"face_secondary_runtime", "face_secondary_preview"}\n'
insert = '''HFN_MACHINE_SCRIPTS = {
    HFN_CANDIDATE_GATE: (
        ".\\\\prepare-hands-feet-nails-fingernail-geometry-candidate.ps1",
        ".\\\\prepare-hands-feet-nails-toenail-geometry-candidate.ps1",
    ),
    HFN_RENDER_GATE: (".\\\\prepare-hands-feet-nails-render-review.ps1",),
}
'''
if module.count(anchor) != 1:
    raise SystemExit("executor HFN constants anchor drifted")
module = module.replace(anchor, anchor + insert, 1)

anchor = '''def _canonical_sha(value: Any, *, field: str, length: int) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise FidelityComponentGapExecutionError(f"{field} is not canonical")
    return text


'''
insert = r'''def _canonical_json_sha(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _appearance_transfer_authority(package: Path) -> tuple[str, str, str]:
    try:
        validated = validate_package(package)
        with zipfile.ZipFile(package, "r") as archive:
            avatar = archive.read("avatar.vrm")
        document, _binary = _read_glb(avatar)
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError, PbrMaterialError) as exc:
        raise FidelityComponentGapExecutionError("HFN appearance authority package is invalid") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    appearance = bodyrig.get("appearanceTransfer") if isinstance(bodyrig, dict) else None
    if not isinstance(appearance, dict) or appearance.get("method") != APPEARANCE_METHOD:
        raise FidelityComponentGapExecutionError("canonical appearanceTransfer authority is missing")
    if (
        appearance.get("canonicalDonorAtlas") is not True
        or appearance.get("sourceDerivedPbrApplied") is not True
        or appearance.get("boundedBaseColorRefinementApplied") is not True
        or appearance.get("generativeAppearanceSynthesis") is not False
        or appearance.get("geometryModified") is not False
    ):
        raise FidelityComponentGapExecutionError("canonical appearanceTransfer authority is invalid")
    return _canonical_json_sha(appearance), str(validated.manifest["id"]), _sha256_file(package)


def _explicit_context_path(value: Any, *, label: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise FidelityComponentGapExecutionError(f"{label} must be supplied explicitly")
    return Path(text).expanduser().resolve()


def _explicit_context_id(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or Path(text).name != text:
        raise FidelityComponentGapExecutionError(f"{label} must be supplied explicitly and canonically")
    return text


'''
if module.count(anchor) != 1:
    raise SystemExit("executor canonical sha helper anchor drifted")
module = module.replace(anchor, anchor + insert, 1)

anchor = '''def build_execution(plan: Mapping[str, Any], *, context: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
'''
hfn = r'''def _hfn_execution(plan: Mapping[str, Any], context: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    package = _need_file(context.get("package_path"), label="HFN gap source package")
    if _sha256_file(package) != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError("HFN source package bytes differ from the Unity gap-plan package SHA")
    appearance_source = _need_file(
        context.get("appearance_source_package_path"),
        label="HFN appearance source package",
    )
    source_appearance_sha, source_body_id, source_package_sha = _appearance_transfer_authority(appearance_source)
    final_appearance_sha, final_body_id, final_package_sha = _appearance_transfer_authority(package)
    if final_package_sha != plan["package_sha256"]:
        raise FidelityComponentGapExecutionError("HFN final package hash changed during appearance authority inspection")
    if source_body_id != final_body_id or final_body_id != plan["body_id"]:
        raise FidelityComponentGapExecutionError("HFN appearance source/final package body identity disagrees with the gap plan")
    if source_appearance_sha != final_appearance_sha:
        raise FidelityComponentGapExecutionError(
            "face-secondary comparison package changed canonical appearanceTransfer authority"
        )

    hfn_root = _explicit_context_path(context.get("hfn_root"), label="HFN root")
    person_id = _explicit_context_id(context.get("person_id"), label="HFN PersonId")
    body_revision = _explicit_context_id(context.get("body_revision"), label="HFN body revision")
    render_dir = _explicit_context_path(context.get("render_dir"), label="HFN render directory")
    human_review_dir = _explicit_context_path(context.get("human_review_dir"), label="HFN human-review directory")
    status = inspect_hfn_continuation(
        root=hfn_root,
        person_id=person_id,
        body_revision=body_revision,
        bodyrig_revision=plan["bodyrig_revision"],
        source_package_path=package,
        source_package_sha256=plan["package_sha256"],
        render_dir=render_dir,
        human_review_dir=human_review_dir,
    )
    gates = status.get("gates")
    actions = status.get("actions")
    if not isinstance(gates, list) or not gates or not isinstance(actions, Mapping):
        raise FidelityComponentGapExecutionError("canonical HFN continuation returned invalid status")
    invalid = next((gate for gate in gates if isinstance(gate, Mapping) and gate.get("state") == "invalid"), None)
    if invalid is not None:
        raise FidelityComponentGapExecutionError(
            f"canonical HFN continuation is invalid: {invalid.get('reason') or 'unknown reason'}"
        )

    pending = next((gate for gate in gates if isinstance(gate, Mapping) and gate.get("state") != "pass"), None)
    if pending is None:
        return {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": "canonical HFN continuation has no further machine action; human/release authority is not automatic",
            "hfn_gate": "complete",
            "hfn_status_reinspect_required_after_execution": False,
            "appearance_source_package_sha256": source_package_sha,
            "appearance_transfer_sha256": final_appearance_sha,
        }
    gate_id = str(pending.get("id") or "")
    action = actions.get(gate_id)
    if not isinstance(action, Mapping):
        raise FidelityComponentGapExecutionError(f"canonical HFN continuation has no action for required gate: {gate_id}")
    reason = str(action.get("reason") or pending.get("reason") or "").strip()
    if not reason:
        raise FidelityComponentGapExecutionError("canonical HFN continuation action has no reason")
    operator_required = action.get("operator_input_required")
    command = str(action.get("command") or "").strip()
    if operator_required is True:
        return {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": reason,
            "operator_command": command,
            "hfn_gate": gate_id,
            "hfn_status_reinspect_required_after_execution": False,
            "appearance_source_package_sha256": source_package_sha,
            "appearance_transfer_sha256": final_appearance_sha,
        }
    if operator_required is not False:
        raise FidelityComponentGapExecutionError("canonical HFN continuation operator boundary is invalid")
    allowed = HFN_MACHINE_SCRIPTS.get(gate_id, ())
    if not allowed or not any(command.startswith(prefix + " ") or command == prefix for prefix in allowed):
        raise FidelityComponentGapExecutionError(
            f"canonical HFN continuation is not at an allowed one-step machine gate: {gate_id}"
        )
    if any(token in command for token in ("\r", "\n", ";", "|", "&&", "||")):
        raise FidelityComponentGapExecutionError("canonical HFN machine command contains unsupported command composition")
    return {
        "mode": "machine-executable",
        "commands": [["pwsh", "-NoProfile", "-Command", command]],
        "operator_input_required": False,
        "reason": reason,
        "hfn_gate": gate_id,
        "hfn_status_reinspect_required_after_execution": True,
        "appearance_source_package_sha256": source_package_sha,
        "appearance_transfer_sha256": final_appearance_sha,
    }


'''
if module.count(anchor) != 1:
    raise SystemExit("executor build_execution anchor drifted")
module = module.replace(anchor, hfn + anchor, 1)

old = '''    elif action_id == "face-secondary-review-composition":
        route = _face_execution(validated, context, root)
    else:
        route = {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": action["reason"],
        }
'''
new = '''    elif action_id == "face-secondary-review-composition":
        route = _face_execution(validated, context, root)
    elif action_id == "source-bound-hfn-continuation":
        route = _hfn_execution(validated, context, root)
    else:
        route = {
            "mode": "operator-stop",
            "commands": [],
            "operator_input_required": True,
            "reason": action["reason"],
        }
'''
if module.count(old) != 1:
    raise SystemExit("executor action routing anchor drifted")
module = module.replace(old, new, 1)
module_path.write_text(module, encoding="utf-8", newline="\n")

# Update test repo scripts for HFN machine routes.
old = '''        "run-high-fidelity-face-secondary-windows-preview.ps1",
    ):
'''
new = '''        "run-high-fidelity-face-secondary-windows-preview.ps1",
        "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1",
        "prepare-hands-feet-nails-toenail-geometry-candidate.ps1",
        "prepare-hands-feet-nails-render-review.ps1",
    ):
'''
if test.count(old) != 1:
    raise SystemExit("executor test repo script anchor drifted")
test = test.replace(old, new, 1)

old = '''def test_hfn_and_human_review_are_hard_operator_stops(tmp_path: Path) -> None:
    root = repo(tmp_path)
    hfn = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context={},
        repo_root=root,
    )
    assert hfn["mode"] == "operator-stop"
    assert hfn["commands"] == []
    assert hfn["operator_input_required"] is True
    assert hfn["reprobe_required_after_execution"] is False
    assert hfn["production_activation"] is False

    human = executor.build_execution(
'''
new = '''def test_hfn_requires_explicit_context_and_human_review_remains_operator_stop(tmp_path: Path) -> None:
    root = repo(tmp_path)
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="appearance source package"):
        executor.build_execution(
            plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
            context={"package_path": str(package)},
            repo_root=root,
        )

    human = executor.build_execution(
'''
if test.count(old) != 1:
    raise SystemExit("executor old HFN stop test anchor drifted")
test = test.replace(old, new, 1)

# Insert focused HFN route tests before execute test.
anchor = '''def test_execute_runs_exactly_one_command_and_requires_windows(monkeypatch: pytest.MonkeyPatch) -> None:
'''
new_tests = r'''def _hfn_context(tmp_path: Path) -> dict[str, str]:
    package = tmp_path / "candidate.mrbody"
    package.write_bytes(b"package")
    source = tmp_path / "source.mrbody"
    source.write_bytes(b"source")
    return {
        "package_path": str(package),
        "appearance_source_package_path": str(source),
        "hfn_root": str(tmp_path / "people"),
        "person_id": "person-" + "1" * 32,
        "body_revision": "body-r0001",
        "render_dir": str(tmp_path / "render"),
        "human_review_dir": str(tmp_path / "human-review"),
    }


def test_hfn_preserves_appearance_authority_and_stops_at_source_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    appearance_sha = "d" * 64
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda path: (
        appearance_sha,
        "performer-42",
        executor._sha256_file(path),
    ))
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **kwargs: {
        "gates": [{"id": executor.HFN_CANDIDATE_GATE, "state": "required", "reason": "source selection required"}],
        "actions": {executor.HFN_CANDIDATE_GATE: {
            "gate": executor.HFN_CANDIDATE_GATE,
            "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 -CaptureId <CAPTURE_ID> -UvEvidence <UV_EVIDENCE_PATH>",
            "operator_input_required": True,
            "reason": "Select exact source-grounded HFN evidence.",
        }},
    })

    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "operator-stop"
    assert result["commands"] == []
    assert result["operator_input_required"] is True
    assert "<CAPTURE_ID>" in result["operator_command"]
    assert "<UV_EVIDENCE_PATH>" in result["operator_command"]
    assert result["appearance_transfer_sha256"] == appearance_sha
    assert result["reprobe_required_after_execution"] is False
    assert result["production_activation"] is False


def test_hfn_rejects_appearance_transfer_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    calls = iter([
        ("a" * 64, "performer-42", executor._sha256_file(Path(context["appearance_source_package_path"]))),
        ("b" * 64, "performer-42", PACKAGE_SHA),
    ])
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda _path: next(calls))
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="changed canonical appearanceTransfer authority"):
        executor.build_execution(
            plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
            context=context,
            repo_root=root,
        )


@pytest.mark.parametrize(
    ("gate_id", "script"),
    [
        (executor.HFN_CANDIDATE_GATE, ".\\prepare-hands-feet-nails-fingernail-geometry-candidate.ps1"),
        (executor.HFN_CANDIDATE_GATE, ".\\prepare-hands-feet-nails-toenail-geometry-candidate.ps1"),
        (executor.HFN_RENDER_GATE, ".\\prepare-hands-feet-nails-render-review.ps1"),
    ],
)
def test_hfn_executes_exactly_one_canonical_machine_step(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, gate_id: str, script: str) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    appearance_sha = "d" * 64
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda path: (
        appearance_sha,
        "performer-42",
        executor._sha256_file(path),
    ))
    command = script + " -Root 'C:\\hfn'"
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **kwargs: {
        "gates": [{"id": gate_id, "state": "required", "reason": "machine gate"}],
        "actions": {gate_id: {
            "gate": gate_id,
            "command": command,
            "operator_input_required": False,
            "reason": "Run one canonical HFN machine step.",
        }},
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "machine-executable"
    assert result["commands"] == [["pwsh", "-NoProfile", "-Command", command]]
    assert result["hfn_gate"] == gate_id
    assert result["hfn_status_reinspect_required_after_execution"] is True
    assert result["reprobe_required_after_execution"] is True
    assert result["human_visual_authority_required"] is True
    assert result["production_activation"] is False


def test_hfn_human_review_never_auto_executes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context = _hfn_context(tmp_path)
    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda path: (
        "d" * 64,
        "performer-42",
        executor._sha256_file(path),
    ))
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **kwargs: {
        "gates": [
            {"id": executor.HFN_CANDIDATE_GATE, "state": "pass"},
            {"id": executor.HFN_RENDER_GATE, "state": "pass"},
            {"id": executor.HFN_HUMAN_GATE, "state": "required", "reason": "human review"},
        ],
        "actions": {executor.HFN_HUMAN_GATE: {
            "gate": executor.HFN_HUMAN_GATE,
            "command": ".\\record-high-fidelity-hfn-review.ps1 -ConfirmDetailChecklist",
            "operator_input_required": True,
            "reason": "Human HFN review is required.",
        }},
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "operator-stop"
    assert result["commands"] == []
    assert "record-high-fidelity-hfn-review.ps1" in result["operator_command"]
    assert result["reprobe_required_after_execution"] is False


'''
if test.count(anchor) != 1:
    raise SystemExit("executor execute-test anchor drifted")
test = test.replace(anchor, new_tests + anchor, 1)
test_path.write_text(test, encoding="utf-8", newline="\n")
