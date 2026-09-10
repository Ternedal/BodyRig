from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str, *, expected: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} matches, found {count}: {old!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def prepend_once(path: str, marker: str, block: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        raise SystemExit(f"{path}: lifecycle status block already exists")
    target.write_text(block.rstrip() + "\n\n" + text, encoding="utf-8")


# Candidate authority remains usable for historical/replay validation by default,
# but callers that intend to enqueue a NEW baseline must explicitly require an
# open lifecycle. The completed v1 marker then blocks before any candidate ref
# geometry is inspected.
replace_exact(
    "bodyrig/ab_baseline_candidates.py",
    'CONTRACT_RELATIVE_PATH = Path("contracts/ab-baseline-candidates-v1.json")\n'
    'EXPECTED_CANDIDATES = {"pbr_v3", "recovery_throughput_v3"}\n',
    'CONTRACT_RELATIVE_PATH = Path("contracts/ab-baseline-candidates-v1.json")\n'
    'CYCLE_STATE_RELATIVE_PATH = Path("contracts/ab-baseline-cycle-state-v1.json")\n'
    'CYCLE_STATE_FORMAT = "bodyrig-ab-baseline-cycle-state"\n'
    'CYCLE_STATE_FIELDS = {\n'
    '    "format",\n'
    '    "version",\n'
    '    "cycle_id",\n'
    '    "state",\n'
    '    "candidate_contract_path",\n'
    '    "candidate_contract_sha256",\n'
    '    "pbr_candidate_revision",\n'
    '    "throughput_candidate_revision",\n'
    '    "promotion_receipt_sha256",\n'
    '    "historical_contract_immutable",\n'
    '    "future_cycle_requires_new_contract_version",\n'
    '    "comparison_only",\n'
    '    "physical_acceptance_authority",\n'
    '    "production_activation",\n'
    '    "release_authority",\n'
    '}\n'
    'EXPECTED_CANDIDATES = {"pbr_v3", "recovery_throughput_v3"}\n',
)
replace_exact(
    "bodyrig/ab_baseline_candidates.py",
    '_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")\n',
    '_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")\n_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")\n',
)

insert_after_contract = '''\n\ndef _assert_cycle_open(repo_root: Path, contract_sha256: str) -> None:\n    path = repo_root / CYCLE_STATE_RELATIVE_PATH\n    if not path.is_file():\n        raise AbBaselineCandidateError(\n            "A/B lifecycle state is missing; current v1 candidate authority cannot be assumed active. "\n            "Create a new versioned candidate contract and lifecycle state before starting another A/B baseline."\n        )\n    try:\n        value = json.loads(path.read_text(encoding="utf-8-sig"))\n    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:\n        raise AbBaselineCandidateError("A/B lifecycle state is not valid UTF-8 JSON") from exc\n    if not isinstance(value, dict) or set(value) != CYCLE_STATE_FIELDS:\n        raise AbBaselineCandidateError("A/B lifecycle state fields do not match the canonical v1 lifecycle contract")\n    if value.get("format") != CYCLE_STATE_FORMAT or value.get("version") != 1:\n        raise AbBaselineCandidateError("A/B lifecycle state format/version mismatch")\n    if value.get("candidate_contract_path") != CONTRACT_RELATIVE_PATH.as_posix():\n        raise AbBaselineCandidateError("A/B lifecycle state does not bind the historical v1 candidate contract")\n    expected_contract_sha = str(value.get("candidate_contract_sha256") or "").strip().lower()\n    if _SHA256_RE.fullmatch(expected_contract_sha) is None or expected_contract_sha != contract_sha256:\n        raise AbBaselineCandidateError("historical A/B v1 candidate contract bytes changed after cycle completion")\n    _revision(value.get("pbr_candidate_revision"), "completed-cycle PBR candidate revision")\n    _revision(value.get("throughput_candidate_revision"), "completed-cycle throughput candidate revision")\n    promotion_sha = str(value.get("promotion_receipt_sha256") or "").strip().lower()\n    if _SHA256_RE.fullmatch(promotion_sha) is None:\n        raise AbBaselineCandidateError("completed A/B cycle lacks canonical promotion receipt SHA-256")\n    if (\n        value.get("historical_contract_immutable") is not True\n        or value.get("future_cycle_requires_new_contract_version") is not True\n        or value.get("comparison_only") is not True\n        or value.get("physical_acceptance_authority") is not False\n        or value.get("production_activation") is not False\n        or value.get("release_authority") is not False\n    ):\n        raise AbBaselineCandidateError("A/B lifecycle state crosses the historical comparison-only authority boundary")\n    state = str(value.get("state") or "").strip()\n    if state == "completed-promoted":\n        raise AbBaselineCandidateError(\n            "A/B candidate cycle v1 is completed/promoted and archived; historical contract "\n            f"{CONTRACT_RELATIVE_PATH.as_posix()} remains immutable at SHA-256 {contract_sha256}. "\n            "Create a new versioned candidate contract and lifecycle state before starting another A/B baseline."\n        )\n    raise AbBaselineCandidateError(\n        f"A/B lifecycle state '{state}' is not an open cycle supported by the v1 launcher; "\n        "create/wire a new versioned candidate contract before starting another A/B baseline."\n    )\n'''
replace_exact(
    "bodyrig/ab_baseline_candidates.py",
    '    return value, hashlib.sha256(raw).hexdigest()\n\n\ndef _validate_contract',
    '    return value, hashlib.sha256(raw).hexdigest()' + insert_after_contract + '\n\ndef _validate_contract',
)
replace_exact(
    "bodyrig/ab_baseline_candidates.py",
    '    expected_throughput_revision: str | None = None,\n) -> dict[str, Any]:\n',
    '    expected_throughput_revision: str | None = None,\n    require_open: bool = False,\n) -> dict[str, Any]:\n',
)
replace_exact(
    "bodyrig/ab_baseline_candidates.py",
    '    contract, contract_sha256 = _load_contract(repo)\n    candidates = _validate_contract(contract)\n\n    branch = _git',
    '    contract, contract_sha256 = _load_contract(repo)\n    candidates = _validate_contract(contract)\n    if require_open:\n        _assert_cycle_open(repo, contract_sha256)\n\n    branch = _git',
)
replace_exact(
    "bodyrig/ab_baseline_candidates.py",
    '    parser.add_argument("--expected-throughput-revision")\n',
    '    parser.add_argument("--expected-throughput-revision")\n    parser.add_argument("--require-open", action="store_true")\n',
)
replace_exact(
    "bodyrig/ab_baseline_candidates.py",
    '            expected_throughput_revision=args.expected_throughput_revision,\n        )\n',
    '            expected_throughput_revision=args.expected_throughput_revision,\n            require_open=args.require_open,\n        )\n',
)

# Both operator entry points explicitly require an open lifecycle. This keeps
# historical validator use available for old receipts while blocking new work.
for path in ("preflight-ab-baseline.ps1", "start-ab-baseline.ps1"):
    replace_exact(
        path,
        '        [string]$ExpectedThroughputRevision = ""\n    )\n',
        '        [string]$ExpectedThroughputRevision = "",\n        [switch]$RequireOpen\n    )\n',
    )
    replace_exact(
        path,
        '        $pythonArgs = @("-m", "bodyrig.ab_baseline_candidates", "--repo-root", $RepoRoot)\n',
        '        $pythonArgs = @("-m", "bodyrig.ab_baseline_candidates", "--repo-root", $RepoRoot)\n'
        '        if ($RequireOpen) { $pythonArgs += "--require-open" }\n',
    )

replace_exact(
    "preflight-ab-baseline.ps1",
    'Write-Host "Validating current main and both active A/B candidate byte contracts..."\n'
    '$pre = Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython\n',
    'Write-Host "Validating A/B lifecycle and current candidate authority..."\n'
    '$pre = Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython -RequireOpen\n',
)
replace_exact(
    "preflight-ab-baseline.ps1",
    '    -ExpectedThroughputRevision $throughputRevision\n',
    '    -ExpectedThroughputRevision $throughputRevision `\n'
    '    -RequireOpen\n',
)

replace_exact(
    "start-ab-baseline.ps1",
    '$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"\n\n'
    '$physicalPreflightScript = Need-File',
    '$BodyRigPython = Need-File -Path $BodyRigPython -Label "BodyRig Python"\n\n'
    'Write-Host "Checking A/B lifecycle before any physical preflight or enqueue..."\n'
    '[void](Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython -RequireOpen)\n\n'
    '$physicalPreflightScript = Need-File',
)
replace_exact(
    "start-ab-baseline.ps1",
    '$preflight = Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython\n',
    '$preflight = Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython -RequireOpen\n',
)

# Regression coverage: exact lifecycle receipt + new-work block, while existing
# historical inspection tests continue to call require_open=False implicitly.
test_path = ROOT / "tests/test_ab_baseline_candidates.py"
test_text = test_path.read_text(encoding="utf-8")
if "test_completed_v1_cycle_blocks_new_baseline_without_rewriting_historical_contract" in test_text:
    raise SystemExit("candidate lifecycle regression test already exists")
test_text += '''\n\ndef test_completed_v1_cycle_blocks_new_baseline_without_rewriting_historical_contract() -> None:\n    lifecycle_path = ROOT / "contracts" / "ab-baseline-cycle-state-v1.json"\n    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))\n    contract_sha = __import__("hashlib").sha256(CONTRACT_PATH.read_bytes()).hexdigest()\n\n    assert lifecycle == {\n        "format": "bodyrig-ab-baseline-cycle-state",\n        "version": 1,\n        "cycle_id": "pbr-v3-throughput-v3-20260910",\n        "state": "completed-promoted",\n        "candidate_contract_path": "contracts/ab-baseline-candidates-v1.json",\n        "candidate_contract_sha256": "fa9ee08c715c216a4dce90e85a2bd699ed56f73eaad5f3fa444cd625110f6cf4",\n        "pbr_candidate_revision": "fe2db94b8ae3be51938a7b302361bcf5fdec5f48",\n        "throughput_candidate_revision": "5fa01deb08399fda64e83db1329d4d2e83ad1bc2",\n        "promotion_receipt_sha256": "2daac171b018b0bdb813fb4698c17fa882ef8d130cd9df0ab7e87d7282c9850d",\n        "historical_contract_immutable": True,\n        "future_cycle_requires_new_contract_version": True,\n        "comparison_only": True,\n        "physical_acceptance_authority": False,\n        "production_activation": False,\n        "release_authority": False,\n    }\n    assert contract_sha == lifecycle["candidate_contract_sha256"]\n    with pytest.raises(ab.AbBaselineCandidateError, match="completed/promoted and archived"):\n        ab._assert_cycle_open(ROOT, contract_sha)\n\n\ndef test_new_baseline_lifecycle_check_rejects_historical_contract_tamper(tmp_path: Path) -> None:\n    repo = tmp_path / "repo"\n    contract = repo / "contracts" / "ab-baseline-candidates-v1.json"\n    state = repo / "contracts" / "ab-baseline-cycle-state-v1.json"\n    contract.parent.mkdir(parents=True)\n    contract.write_text("tampered", encoding="utf-8")\n    lifecycle = json.loads((ROOT / "contracts" / "ab-baseline-cycle-state-v1.json").read_text(encoding="utf-8"))\n    state.write_text(json.dumps(lifecycle), encoding="utf-8")\n    with pytest.raises(ab.AbBaselineCandidateError, match="historical A/B v1 candidate contract bytes changed"):\n        ab._assert_cycle_open(repo, "0" * 64)\n'''
test_path.write_text(test_text.rstrip() + "\n", encoding="utf-8")

launcher_test = ROOT / "tests/test_ab_baseline_launcher_contract.py"
launcher_text = launcher_test.read_text(encoding="utf-8")
if "test_new_baseline_paths_require_open_versioned_cycle_before_physical_work" in launcher_text:
    raise SystemExit("launcher lifecycle regression test already exists")
launcher_text += '''\n\ndef test_new_baseline_paths_require_open_versioned_cycle_before_physical_work() -> None:\n    for source in (SCRIPT, PREFLIGHT):\n        assert '[switch]$RequireOpen' in source\n        assert 'if ($RequireOpen) { $pythonArgs += "--require-open" }' in source\n    assert 'Checking A/B lifecycle before any physical preflight or enqueue' in SCRIPT\n    assert SCRIPT.index('-RequireOpen') < SCRIPT.index('preflight-ab-baseline.ps1')\n    assert 'Validating A/B lifecycle and current candidate authority' in PREFLIGHT\n    assert 'Invoke-CandidateAuthority -RepoRoot $repoRoot -Python $BodyRigPython -RequireOpen' in PREFLIGHT\n'''
launcher_test.write_text(launcher_text.rstrip() + "\n", encoding="utf-8")

status_block = '''> **A/B v1 lifecycle — completed 2026-09-10.** The PBR-v3 / recovery-throughput-v3 shared comparison cycle is finished and promoted under receipt SHA-256 `2daac171b018b0bdb813fb4698c17fa882ef8d130cd9df0ab7e87d7282c9850d`. `contracts/ab-baseline-candidates-v1.json` is now immutable historical evidence; it is not an active candidate contract. `contracts/ab-baseline-cycle-state-v1.json` records that closure. `start-ab-baseline.ps1` and `preflight-ab-baseline.ps1` fail closed before physical work until a **new versioned candidate contract/lifecycle** is introduced. This retirement grants no physical acceptance, production activation, or release authority.'''
for path in (
    "HANDOFF.md",
    "docs/AB_BASELINE.md",
    "docs/PBR_AB_PHYSICAL_REVIEW.md",
    "docs/THROUGHPUT_PLAN_BOUND_REVIEW.md",
):
    prepend_once(path, "A/B v1 lifecycle — completed 2026-09-10", status_block)

# Remove one-off patch machinery from the resulting branch tree.
for relative in (
    "tools/_retire_ab_cycle_v1_patch.py",
    ".github/workflows/_retire_ab_cycle_v1_apply.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()

print("A/B v1 retirement patch applied")
