from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str, *, expected: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} occurrences, found {count}: {old!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# 1. PBR body-job source: the canonical fidelity review is the Person Library
# receipt already hash-bound by job.body_review_sha256. The per-job fidelity
# directory contains renderer evidence and must not require an undocumented
# duplicate review.json mirror.
replace_exact(
    "bodyrig/pbr_ab_body_job_source.py",
    '    if not (fidelity_dir / "review.json").is_file():\n'
    '        raise PbrAbBodyJobSourceError("succeeded A/B body job lacks fidelity review evidence")\n',
    '    # The authoritative body fidelity review is persisted under the Person Library\n'
    '    # and verified below against job.body_review_sha256. The per-job fidelity\n'
    '    # directory is renderer evidence only; no duplicate review.json mirror is required.\n',
)

# Make the existing valid fixture prove the real producer shape (no mirror).
replace_exact(
    "tests/test_pbr_ab_body_job_source.py",
    '    _write_json(fidelity / "review.json", {"format": "fixture"})\n',
    '',
)
replace_exact(
    "tests/test_pbr_ab_body_job_source.py",
    '    result = source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo, expected_revision=REVISION)\n\n'
    '    assert result["format"] == source.FORMAT\n',
    '    assert not (job_root / "fidelity-review" / "review.json").exists()\n'
    '    result = source.inspect_body_job_source(job_id=JOB_ID, repo_root=repo, expected_revision=REVISION)\n\n'
    '    assert result["format"] == source.FORMAT\n',
)

# 2. Strict PBR runner: parenthesize the array concatenation at both fetches.
replace_exact(
    "run-pbr-ab-physical-review.ps1",
    '[void](Invoke-Git -Arguments @("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs -Step ',
    '[void](Invoke-Git -Arguments (@("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs) -Step ',
    expected=2,
)

runner_test = ROOT / "tests/test_pbr_ab_physical_runner_contract.py"
runner_text = runner_test.read_text(encoding="utf-8")
runner_add = '''\n\ndef test_runner_parenthesizes_both_fetch_array_concatenations() -> None:\n    good = 'Invoke-Git -Arguments (@("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs) -Step'\n    bad = 'Invoke-Git -Arguments @("-C",$repoRoot,"fetch","--no-tags","origin") + $fetchSpecs -Step'\n    assert RUNNER.count(good) == 2\n    assert bad not in RUNNER\n'''
if "test_runner_parenthesizes_both_fetch_array_concatenations" in runner_text:
    raise SystemExit("runner regression test already exists")
runner_test.write_text(runner_text.rstrip() + runner_add + "\n", encoding="utf-8")

# 3. Generic watcher: optional checkpoint detail must be StrictMode-safe.
replace_exact(
    "watch-body-build.ps1",
    '                    [pscustomobject]@{\n'
    '                        Root = $root\n'
    '                        Path = $_.FullName\n'
    '                        SourceIndex = [int]$value.source_index\n'
    '                        State = [string]$value.state\n'
    '                        Detail = [string]$value.detail\n'
    '                    }\n',
    '                    $detail = ""\n'
    '                    if ($value.PSObject.Properties.Name -contains "detail") {\n'
    '                        $detail = [string]$value.detail\n'
    '                    }\n'
    '                    [pscustomobject]@{\n'
    '                        Root = $root\n'
    '                        Path = $_.FullName\n'
    '                        SourceIndex = [int]$value.source_index\n'
    '                        State = [string]$value.state\n'
    '                        Detail = $detail\n'
    '                    }\n',
)

watch_contract = ROOT / "tests/test_watch_body_build_contract.py"
watch_text = watch_contract.read_text(encoding="utf-8")
watch_add = '''\n\ndef test_monitor_treats_checkpoint_detail_as_optional_under_strictmode() -> None:\n    assert '$value.PSObject.Properties.Name -contains "detail"' in SCRIPT\n    assert 'Detail = $detail' in SCRIPT\n    assert 'Detail = [string]$value.detail' not in SCRIPT\n'''
if "test_monitor_treats_checkpoint_detail_as_optional_under_strictmode" in watch_text:
    raise SystemExit("watcher contract regression test already exists")
watch_contract.write_text(watch_text.rstrip() + watch_add + "\n", encoding="utf-8")

runtime_test = ROOT / "tests/test_watch_body_build_optional_detail_runtime.py"
runtime_test.write_text(r'''from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "watch-body-build.ps1"
JOB_ID = "job-" + "1" * 32
PERSON_ID = "person-" + "2" * 32
REVISION = "3" * 40


def test_missing_checkpoint_detail_does_not_crash_strictmode_monitor(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("Windows path translation is exercised by the production-OS CI job")
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is required")

    data_root = tmp_path / "data"
    local = tmp_path / "local"
    temp_root = tmp_path / "temp"
    job_root = data_root / "ui-jobs" / JOB_ID
    source_parent = tmp_path / PERSON_ID
    checkpoint_root = source_parent / "bodyrig-recovery-checkpoints"
    staging = temp_root / "bodyrig-wsl-recovery-optional-detail"
    for path in (job_root, local, checkpoint_root, staging):
        path.mkdir(parents=True, exist_ok=True)

    source = source_parent / "segment.mp4"
    source.write_bytes(b"fixture")
    drive = source.drive.rstrip(":").lower()
    tail = source.as_posix()[3:] if source.as_posix()[1:3] == ":/" else source.as_posix().lstrip("/")
    wsl_source = f"/mnt/{drive}/{tail}"

    (checkpoint_root / "segment-01.status.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-recovery-segment-status",
                "version": 1,
                "source_index": 0,
                "state": "running",
            }
        ),
        encoding="utf-8",
    )
    (checkpoint_root / "segment-01.log").write_text("Tracking : segment-0 50%\n", encoding="utf-8")
    (staging / "request.json").write_text(json.dumps({"sources": [wsl_source]}), encoding="utf-8")
    (staging / "stderr.log").write_text("", encoding="utf-8")

    job = {
        "format": "bodyrig-ui-job",
        "version": 1,
        "job_id": JOB_ID,
        "kind": "body-build",
        "person_id": PERSON_ID,
        "status": "running",
        "created_utc": "2026-09-10T10:00:00Z",
        "started_utc": "2026-09-10T10:00:01Z",
        "completed_utc": None,
        "bodyrig_revision": REVISION,
        "clone_output": str(job_root / "clone-output"),
        "acceptance_dir": str(job_root / "acceptance"),
        "fidelity_dir": str(job_root / "fidelity-review"),
        "log_path": str(job_root / "missing.log"),
    }
    (job_root / "job.json").write_text(json.dumps(job), encoding="utf-8")

    env = os.environ.copy()
    env["BODYRIG_DATA_DIR"] = str(data_root)
    env["LOCALAPPDATA"] = str(local)
    env["TEMP"] = str(temp_root)
    env["TMP"] = str(temp_root)

    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(SCRIPT), "-JobId", JOB_ID, "-Once", "-NoClear"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Recovery: segment 1/1" in result.stdout
    assert "state: running" in result.stdout
''', encoding="utf-8")

# 4. Throughput transition: suppress updater diagnostics in the internal machine
# result stream and make the outer wrapper select exactly one canonical receipt
# rather than assuming every success-stream item is JSON.
replace_exact(
    "start-throughput-candidate-from-ab-plan-internal.ps1",
    '& $updateScript -Branch $throughputRef -NoBrowser -SkipPlan\n',
    '$null = & $updateScript -Branch $throughputRef -NoBrowser -SkipPlan\n',
)

replace_exact(
    "start-throughput-candidate-from-ab-plan.ps1",
    'if ($raw.Count -ne 1) { throw "Internal throughput candidate launcher did not return exactly one machine-readable result." }\n'
    'try { $started = ([string]$raw[0]) | ConvertFrom-Json -Depth 30 }\n'
    'catch { throw "Internal throughput candidate launcher returned unreadable JSON." }\n',
    '$machineResults = @(\n'
    '    foreach ($item in $raw) {\n'
    '        $text = [string]$item\n'
    '        if ([string]::IsNullOrWhiteSpace($text)) { continue }\n'
    '        try { $candidateResult = $text | ConvertFrom-Json -Depth 30 } catch { continue }\n'
    '        $fields = @($candidateResult.PSObject.Properties.Name)\n'
    '        if (\n'
    '            $fields -contains "format" -and\n'
    '            $fields -contains "version" -and\n'
    '            [string]$candidateResult.format -eq "bodyrig-throughput-candidate-run-plan" -and\n'
    '            [int]$candidateResult.version -eq 1\n'
    '        ) {\n'
    '            $candidateResult\n'
    '        }\n'
    '    }\n'
    ')\n'
    'if ($machineResults.Count -ne 1) {\n'
    '    throw "Internal throughput candidate launcher did not return exactly one canonical machine-readable result."\n'
    '}\n'
    '$started = $machineResults[0]\n',
)
replace_exact(
    "start-throughput-candidate-from-ab-plan.ps1",
    '[Console]::Out.WriteLine(([string]$raw[0]))\n',
    '[Console]::Out.WriteLine(($started | ConvertTo-Json -Depth 30 -Compress))\n',
)

throughput_test = ROOT / "tests/test_throughput_candidate_from_ab_plan_contract.py"
throughput_text = throughput_test.read_text(encoding="utf-8")
throughput_text = throughput_text.replace(
    "    assert '& $updateScript -Branch $throughputRef -NoBrowser -SkipPlan' in INTERNAL\n",
    "    assert '$null = & $updateScript -Branch $throughputRef -NoBrowser -SkipPlan' in INTERNAL\n",
)
throughput_add = '''\n\ndef test_canonical_launcher_ignores_diagnostics_and_selects_one_typed_machine_result() -> None:\n    assert '$machineResults = @(' in WRAPPER\n    assert '$candidateResult.PSObject.Properties.Name' in WRAPPER\n    assert 'bodyrig-throughput-candidate-run-plan' in WRAPPER\n    assert 'exactly one canonical machine-readable result' in WRAPPER\n    assert '$started = $machineResults[0]' in WRAPPER\n    assert '[Console]::Out.WriteLine(($started | ConvertTo-Json -Depth 30 -Compress))' in WRAPPER\n    assert '$raw.Count -ne 1' not in WRAPPER\n'''
if "test_canonical_launcher_ignores_diagnostics_and_selects_one_typed_machine_result" in throughput_text:
    raise SystemExit("throughput regression test already exists")
throughput_test.write_text(throughput_text.rstrip() + throughput_add + "\n", encoding="utf-8")

# Remove this one-off patch mechanism from the final branch diff. The running
# workflow can delete its own source/workflow after it has started.
for relative in (
    "tools/_post_physical_ab_hardening_patch.py",
    ".github/workflows/_post_physical_ab_hardening_apply.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()

print("post-physical A/B hardening patch applied")
