from pathlib import Path

root = Path(__file__).resolve().parents[1]
module_path = root / "bodyrig" / "fidelity_component_gap_executor.py"
test_path = root / "tests" / "test_fidelity_component_gap_executor.py"
module = module_path.read_text(encoding="utf-8")
test = test_path.read_text(encoding="utf-8")

old = '''    if final_package_sha != plan["package_sha256"]:\n        raise FidelityComponentGapExecutionError("HFN final package hash changed during appearance authority inspection")\n    if source_body_id != final_body_id or final_body_id != plan["body_id"]:\n'''
new = '''    if final_package_sha != plan["package_sha256"]:\n        raise FidelityComponentGapExecutionError("HFN final package hash changed during appearance authority inspection")\n    if source_package_sha == final_package_sha:\n        raise FidelityComponentGapExecutionError(\n            "HFN appearance preservation requires a distinct pre-face-secondary source package"\n        )\n    if source_body_id != final_body_id or final_body_id != plan["body_id"]:\n'''
if module.count(old) != 1:
    raise SystemExit("HFN appearance source distinction anchor drifted")
module = module.replace(old, new, 1)

old = '''        "commands": [["pwsh", "-NoProfile", "-Command", command]],\n        "operator_input_required": False,\n        "reason": reason,\n'''
new = '''        "commands": [["pwsh", "-NoProfile", "-Command", command]],\n        "working_directory": str(repo_root),\n        "operator_input_required": False,\n        "reason": reason,\n'''
if module.count(old) != 1:
    raise SystemExit("HFN working-directory route anchor drifted")
module = module.replace(old, new, 1)

old = '''    completed = runner(commands[0], check=False)\n    code = int(getattr(completed, "returncode", 1))\n'''
new = '''    runner_kwargs: dict[str, Any] = {"check": False}\n    working_directory = execution.get("working_directory")\n    if working_directory is not None:\n        workdir = os.path.abspath(os.path.expanduser(str(working_directory)))\n        if not os.path.isdir(workdir):\n            raise FidelityComponentGapExecutionError("component gap execution working directory is missing")\n        runner_kwargs["cwd"] = workdir\n    completed = runner(commands[0], **runner_kwargs)\n    code = int(getattr(completed, "returncode", 1))\n'''
if module.count(old) != 1:
    raise SystemExit("executor runner working-directory anchor drifted")
module = module.replace(old, new, 1)
module_path.write_text(module, encoding="utf-8", newline="\n")

old = '''    assert result["commands"] == [["pwsh", "-NoProfile", "-Command", command]]\n    assert result["hfn_gate"] == gate_id\n'''
new = '''    assert result["commands"] == [["pwsh", "-NoProfile", "-Command", command]]\n    assert result["working_directory"] == str(root)\n    assert result["hfn_gate"] == gate_id\n'''
if test.count(old) != 1:
    raise SystemExit("HFN machine-step test anchor drifted")
test = test.replace(old, new, 1)

anchor = '''def test_hfn_rejects_appearance_transfer_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:\n'''
insert = '''def test_hfn_rejects_trivial_same_package_appearance_self_proof(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:\n    root = repo(tmp_path)\n    context = _hfn_context(tmp_path)\n    context["appearance_source_package_path"] = context["package_path"]\n    monkeypatch.setattr(executor, "_appearance_transfer_authority", lambda path: (\n        "d" * 64,\n        "performer-42",\n        executor._sha256_file(path),\n    ))\n    with pytest.raises(executor.FidelityComponentGapExecutionError, match="distinct pre-face-secondary source package"):\n        executor.build_execution(\n            plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),\n            context=context,\n            repo_root=root,\n        )\n\n\n'''
if test.count(anchor) != 1:
    raise SystemExit("HFN self-proof test anchor drifted")
test = test.replace(anchor, insert + anchor, 1)

anchor = '''def test_execute_runs_exactly_one_command_and_requires_windows(monkeypatch: pytest.MonkeyPatch) -> None:\n'''
insert = '''def test_execute_honors_exact_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:\n    monkeypatch.setattr(executor.os, "name", "nt")\n    calls: list[tuple[list[str], str | None]] = []\n\n    class Result:\n        returncode = 0\n\n    def runner(argv: list[str], *, check: bool, cwd: str | None = None):\n        assert check is False\n        calls.append((argv, cwd))\n        return Result()\n\n    command = ["pwsh", "-NoProfile", "-Command", ".\\\\prepare-hands-feet-nails-render-review.ps1 -PackagePath 'x'"]\n    result = executor.execute(\n        {"mode": "machine-executable", "commands": [command], "working_directory": str(tmp_path)},\n        runner=runner,\n    )\n    assert result["executed"] is True\n    assert calls == [(command, str(tmp_path.resolve()))]\n\n\n'''
if test.count(anchor) != 1:
    raise SystemExit("executor working-directory test anchor drifted")
test = test.replace(anchor, insert + anchor, 1)
test_path.write_text(test, encoding="utf-8", newline="\n")
