from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement target, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


preview_jobs = "bodyrig/high_fidelity_preview_jobs.py"
resolver = '''\n    def resolve_succeeded_candidate(\n        self,\n        *,\n        canonical_body_id: str,\n        bodyrig_revision: str,\n        candidate_package_sha256: str,\n    ) -> dict[str, Any]:\n        body_id = str(canonical_body_id or "").strip()\n        revision = str(bodyrig_revision or "").strip().lower()\n        candidate_sha = str(candidate_package_sha256 or "").strip().lower()\n        if not body_id or len(body_id) > 160:\n            raise HighFidelityPreviewError("canonical body id is missing or invalid for preview resolution")\n        if not SHA_RE.fullmatch(revision):\n            raise HighFidelityPreviewError("BodyRig revision is invalid for preview resolution")\n        if len(candidate_sha) != 64 or any(ch not in "0123456789abcdef" for ch in candidate_sha):\n            raise HighFidelityPreviewError("candidate package SHA-256 is invalid for preview resolution")\n\n        with self._lock:\n            root = _store_root()\n            if not root.exists():\n                raise HighFidelityPreviewError("no high-fidelity preview store exists for exact candidate resolution")\n            matches: list[dict[str, Any]] = []\n            for path in root.glob("*/job.json"):\n                try:\n                    job = _read_job(path)\n                except HighFidelityPreviewError:\n                    continue\n                if (\n                    job.get("status") != "succeeded"\n                    or str(job.get("canonical_body_id") or "").strip() != body_id\n                    or str(job.get("bodyrig_revision") or "").strip().lower() != revision\n                ):\n                    continue\n                try:\n                    public = _public(job)\n                except HighFidelityPreviewError as exc:\n                    raise HighFidelityPreviewError(\n                        "matching succeeded high-fidelity preview lineage is invalid"\n                    ) from exc\n                if str(public.get("candidate_package_sha256") or "").strip().lower() == candidate_sha:\n                    matches.append(public)\n\n            if not matches:\n                raise HighFidelityPreviewError(\n                    "no succeeded high-fidelity preview matches the exact body, BodyRig revision and candidate package"\n                )\n            if len(matches) != 1:\n                raise HighFidelityPreviewError(\n                    "multiple succeeded high-fidelity previews match the exact candidate; pass preview_job_id explicitly"\n                )\n            return matches[0]\n\n'''
replace_once(
    preview_jobs,
    '    def get(self, job_id: str) -> dict[str, Any]:\n',
    resolver + '    def get(self, job_id: str) -> dict[str, Any]:\n',
)

executor = "bodyrig/fidelity_component_gap_executor.py"
replace_once(
    executor,
    '''    preview_job_id = str(context.get("preview_job_id") or "").strip()\n    if not preview_job_id:\n        raise FidelityComponentGapExecutionError("face-secondary execution requires preview_job_id for canonical continuation lineage")\n    try:\n        preview = preview_manager.get(preview_job_id)\n    except Exception as exc:\n        raise FidelityComponentGapExecutionError("face-secondary preview lineage is unavailable or invalid") from exc\n''',
    '''    preview_job_id = str(context.get("preview_job_id") or "").strip()\n    preview_lineage_resolution = "explicit"\n    try:\n        if preview_job_id:\n            preview = preview_manager.get(preview_job_id)\n        else:\n            preview = preview_manager.resolve_succeeded_candidate(\n                canonical_body_id=plan["body_id"],\n                bodyrig_revision=plan["bodyrig_revision"],\n                candidate_package_sha256=plan["package_sha256"],\n            )\n            preview_job_id = str(preview.get("job_id") or "").strip()\n            preview_lineage_resolution = "auto-exact-candidate"\n    except Exception as exc:\n        raise FidelityComponentGapExecutionError("face-secondary preview lineage is unavailable or invalid") from exc\n    if not preview_job_id:\n        raise FidelityComponentGapExecutionError("resolved face-secondary preview lineage has no job id")\n''',
)
replace_once(
    executor,
    '''    if preview_revision != plan["bodyrig_revision"]:\n        raise FidelityComponentGapExecutionError("face-secondary preview targets a different BodyRig revision than the gap plan")\n    status = inspect_continuation(preview_job_id)\n''',
    '''    if preview_revision != plan["bodyrig_revision"]:\n        raise FidelityComponentGapExecutionError("face-secondary preview targets a different BodyRig revision than the gap plan")\n    preview_candidate_sha = _canonical_sha(\n        preview.get("candidate_package_sha256"),\n        field="preview candidate package SHA",\n        length=64,\n    )\n    if preview_candidate_sha != plan["package_sha256"]:\n        raise FidelityComponentGapExecutionError(\n            "face-secondary preview targets a different candidate package than the Unity gap plan"\n        )\n    status = inspect_continuation(preview_job_id)\n''',
)
replace_once(
    executor,
    '''        "preview_bodyrig_revision": preview_revision,\n    }\n''',
    '''        "preview_bodyrig_revision": preview_revision,\n        "preview_candidate_package_sha256": preview_candidate_sha,\n        "preview_lineage_resolution": preview_lineage_resolution,\n    }\n''',
)

replace_once(
    "tests/test_fidelity_component_gap_executor.py",
    '''        "bodyrig_revision": REVISION,\n        "status": "succeeded",\n''',
    '''        "bodyrig_revision": REVISION,\n        "candidate_package_sha256": PACKAGE_SHA,\n        "status": "succeeded",\n''',
)

face_test = "tests/test_component_gap_face_preview_lineage.py"
replace_once(
    face_test,
    '''def preview(*, body_id: str = BODY_ID, revision: str = REVISION, status: str = "succeeded") -> dict:\n''',
    '''def preview(\n    *,\n    body_id: str = BODY_ID,\n    revision: str = REVISION,\n    candidate_sha: str = "b" * 64,\n    status: str = "succeeded",\n) -> dict:\n''',
)
replace_once(
    face_test,
    '''        "bodyrig_revision": revision,\n        "status": status,\n''',
    '''        "bodyrig_revision": revision,\n        "candidate_package_sha256": candidate_sha,\n        "status": status,\n''',
)
replace_once(
    face_test,
    '''    assert result["preview_bodyrig_revision"] == REVISION\n    assert result["preview_job_id"] == "hfpreview-" + "1" * 32\n''',
    '''    assert result["preview_bodyrig_revision"] == REVISION\n    assert result["preview_candidate_package_sha256"] == "b" * 64\n    assert result["preview_lineage_resolution"] == "explicit"\n    assert result["preview_job_id"] == "hfpreview-" + "1" * 32\n''',
)
append = '''\n\ndef test_face_execution_rejects_cross_candidate_preview_before_continuation(\n    monkeypatch: pytest.MonkeyPatch, tmp_path: Path\n) -> None:\n    root = repo(tmp_path)\n    monkeypatch.setattr(executor.preview_manager, "get", lambda _job: preview(candidate_sha="c" * 64))\n    called = False\n\n    def inspect(_job: str) -> dict:\n        nonlocal called\n        called = True\n        raise AssertionError("continuation must not be inspected for the wrong candidate package")\n\n    monkeypatch.setattr(executor, "inspect_continuation", inspect)\n    with pytest.raises(executor.FidelityComponentGapExecutionError, match="different candidate package"):\n        executor.build_execution(plan(), context={"preview_job_id": "hfpreview-" + "1" * 32}, repo_root=root)\n    assert called is False\n\n\ndef test_face_execution_auto_resolves_only_exact_candidate_lineage(\n    monkeypatch: pytest.MonkeyPatch, tmp_path: Path\n) -> None:\n    root = repo(tmp_path)\n    current_package, _face_runtime = configure_continuation(monkeypatch, tmp_path)\n    calls: list[dict[str, str]] = []\n\n    def resolve(**kwargs: str) -> dict:\n        calls.append(kwargs)\n        return preview()\n\n    monkeypatch.setattr(executor.preview_manager, "resolve_succeeded_candidate", resolve)\n    monkeypatch.setattr(\n        executor.preview_manager,\n        "get",\n        lambda _job: (_ for _ in ()).throw(AssertionError("explicit get must not run during auto-resolution")),\n    )\n\n    result = executor.build_execution(plan(), context={}, repo_root=root)\n\n    assert calls == [{\n        "canonical_body_id": BODY_ID,\n        "bodyrig_revision": REVISION,\n        "candidate_package_sha256": "b" * 64,\n    }]\n    assert result["preview_lineage_resolution"] == "auto-exact-candidate"\n    assert result["preview_candidate_package_sha256"] == "b" * 64\n    assert str(current_package.resolve()) in result["commands"][0]\n'''
with Path(face_test).open("a", encoding="utf-8", newline="\n") as handle:
    handle.write(append)

Path("tests/test_high_fidelity_preview_candidate_resolution.py").write_text('''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nimport pytest\n\nimport bodyrig.high_fidelity_preview_jobs as preview_jobs\n\n\nREVISION = "a" * 40\nBODY_ID = "performer-42"\nCANDIDATE_SHA = "b" * 64\n\n\ndef write_job(root: Path, job_id: str, *, candidate_sha: str = CANDIDATE_SHA) -> None:\n    path = root / job_id / "job.json"\n    path.parent.mkdir(parents=True)\n    path.write_text(json.dumps({\n        "format": preview_jobs.FORMAT,\n        "version": 1,\n        "job_id": job_id,\n        "status": "succeeded",\n        "canonical_body_id": BODY_ID,\n        "bodyrig_revision": REVISION,\n        "candidate_package_sha256": candidate_sha,\n    }), encoding="utf-8")\n\n\ndef configure(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:\n    monkeypatch.setattr(preview_jobs, "_store_root", lambda: root)\n    monkeypatch.setattr(preview_jobs, "_public", lambda job: dict(job))\n\n\ndef test_resolve_succeeded_candidate_requires_one_exact_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:\n    configure(monkeypatch, tmp_path)\n    write_job(tmp_path, "hfpreview-" + "1" * 32)\n    write_job(tmp_path, "hfpreview-" + "2" * 32, candidate_sha="c" * 64)\n\n    result = preview_jobs.manager.resolve_succeeded_candidate(\n        canonical_body_id=BODY_ID,\n        bodyrig_revision=REVISION,\n        candidate_package_sha256=CANDIDATE_SHA,\n    )\n\n    assert result["job_id"] == "hfpreview-" + "1" * 32\n\n\ndef test_resolve_succeeded_candidate_fails_closed_on_zero_or_ambiguous_matches(\n    monkeypatch: pytest.MonkeyPatch, tmp_path: Path\n) -> None:\n    configure(monkeypatch, tmp_path)\n    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="no succeeded"):\n        preview_jobs.manager.resolve_succeeded_candidate(\n            canonical_body_id=BODY_ID,\n            bodyrig_revision=REVISION,\n            candidate_package_sha256=CANDIDATE_SHA,\n        )\n\n    write_job(tmp_path, "hfpreview-" + "1" * 32)\n    write_job(tmp_path, "hfpreview-" + "2" * 32)\n    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="multiple succeeded"):\n        preview_jobs.manager.resolve_succeeded_candidate(\n            canonical_body_id=BODY_ID,\n            bodyrig_revision=REVISION,\n            candidate_package_sha256=CANDIDATE_SHA,\n        )\n\n\ndef test_resolve_succeeded_candidate_rejects_invalid_matching_lineage(\n    monkeypatch: pytest.MonkeyPatch, tmp_path: Path\n) -> None:\n    monkeypatch.setattr(preview_jobs, "_store_root", lambda: tmp_path)\n    write_job(tmp_path, "hfpreview-" + "1" * 32)\n\n    def invalid(_job: dict) -> dict:\n        raise preview_jobs.HighFidelityPreviewError("tampered")\n\n    monkeypatch.setattr(preview_jobs, "_public", invalid)\n    with pytest.raises(preview_jobs.HighFidelityPreviewError, match="matching succeeded.*invalid"):\n        preview_jobs.manager.resolve_succeeded_candidate(\n            canonical_body_id=BODY_ID,\n            bodyrig_revision=REVISION,\n            candidate_package_sha256=CANDIDATE_SHA,\n        )\n''', encoding="utf-8", newline="\n")
