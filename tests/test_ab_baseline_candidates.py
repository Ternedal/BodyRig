from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import bodyrig.ab_baseline_candidates as ab


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "ab-baseline-candidates-v1.json"
MAIN = "a" * 40
PBR = "b" * 40
THROUGHPUT = "c" * 40


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_reviewed_contract_binds_every_active_candidate_blob() -> None:
    value = _contract()
    normalized = ab._validate_contract(value)

    assert set(normalized) == {"pbr_v2", "recovery_throughput_v3"}
    assert len(normalized["pbr_v2"]["files"]) == 3
    assert len(normalized["recovery_throughput_v3"]["files"]) == 18
    assert normalized["pbr_v2"]["files"]["bodyrig/bridges/sith_pbr_material.py"] == (
        "ff79c39f66d44f6649a819da9d75adc35609d0da"
    )
    assert normalized["recovery_throughput_v3"]["files"]["bodyrig/bridges/hmr2_checkpoint_bridge.py"] == (
        "853414c46568cfeb8d00fbb00c51acf491d78dbd"
    )
    assert normalized["recovery_throughput_v3"]["files"]["bodyrig/bridges/hmr2_config.py"] == (
        "d310d972b25edec83552babfd2e7e0626698be3e"
    )
    assert normalized["recovery_throughput_v3"]["files"]["bodyrig/bridges/hmr2_resume_bridge.py"] == (
        "d8ddd983cc9a6275d424add81ed530326cdf9c0a"
    )


def test_contract_cannot_grant_physical_or_production_authority() -> None:
    value = _contract()
    value["production_activation"] = True
    with pytest.raises(ab.AbBaselineCandidateError, match="cannot grant physical or production authority"):
        ab._validate_contract(value)


def test_contract_rejects_unreviewed_candidate_or_unsafe_ref() -> None:
    value = _contract()
    value["candidates"]["surprise"] = copy.deepcopy(value["candidates"]["pbr_v2"])
    with pytest.raises(ab.AbBaselineCandidateError, match="exactly the PBR v2 and throughput v3"):
        ab._validate_contract(value)

    value = _contract()
    value["candidates"]["pbr_v2"]["ref"] = "candidate/../wrong"
    with pytest.raises(ab.AbBaselineCandidateError, match="safe candidate branch ref"):
        ab._validate_contract(value)


def test_inspection_requires_clean_exact_main_and_one_commit_candidate_deltas(monkeypatch) -> None:
    contract = _contract()
    normalized = ab._validate_contract(contract)
    revision_by_name = {"pbr_v2": PBR, "recovery_throughput_v3": THROUGHPUT}
    name_by_ref = {entry["ref"]: name for name, entry in normalized.items()}

    monkeypatch.setattr(ab, "_load_contract", lambda _repo: (contract, "d" * 64))
    monkeypatch.setattr(ab, "_fetch_authority_refs", lambda _repo, _candidates: None)

    def fake_git(_repo: Path, *args: str) -> str:
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD") or args == ("rev-parse", "refs/remotes/origin/main"):
            return MAIN
        if len(args) == 2 and args[0] == "rev-parse" and args[1].startswith("refs/remotes/origin/"):
            ref = args[1][len("refs/remotes/origin/") :]
            return revision_by_name[name_by_ref[ref]]
        if len(args) == 3 and args[:2] == ("rev-list", "--count"):
            left, right = args[2].split("..", 1)
            return "1" if left == MAIN and right in {PBR, THROUGHPUT} else "0"
        if len(args) == 3 and args[0] == "merge-base":
            return MAIN
        if len(args) == 6 and args[:3] == ("diff", "--name-only", "--no-renames"):
            revision = args[4]
            name = "pbr_v2" if revision == PBR else "recovery_throughput_v3"
            return "\n".join(normalized[name]["files"])
        raise AssertionError(f"unexpected git invocation: {args!r}")

    monkeypatch.setattr(ab, "_git", fake_git)

    def fake_tree_blob(_repo: Path, revision: str, path: str) -> str:
        name = "pbr_v2" if revision == PBR else "recovery_throughput_v3"
        return normalized[name]["files"][path]

    monkeypatch.setattr(ab, "_tree_blob", fake_tree_blob)

    result = ab.inspect_candidate_authority(repo_root=ROOT)
    assert result["main_revision"] == MAIN
    assert result["candidates"]["pbr_v2"]["revision"] == PBR
    assert result["candidates"]["recovery_throughput_v3"]["revision"] == THROUGHPUT
    assert result["comparison_only"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_post_enqueue_expected_revision_check_rejects_ref_drift(monkeypatch) -> None:
    contract = _contract()
    normalized = ab._validate_contract(contract)
    monkeypatch.setattr(ab, "_load_contract", lambda _repo: (contract, "d" * 64))
    monkeypatch.setattr(ab, "_fetch_authority_refs", lambda _repo, _candidates: None)

    def fake_git(_repo: Path, *args: str) -> str:
        if args == ("branch", "--show-current"):
            return "main"
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD") or args == ("rev-parse", "refs/remotes/origin/main"):
            return MAIN
        if args == ("rev-parse", f"refs/remotes/origin/{normalized['pbr_v2']['ref']}"):
            return PBR
        if args == ("rev-parse", f"refs/remotes/origin/{normalized['recovery_throughput_v3']['ref']}"):
            return THROUGHPUT
        raise AssertionError(f"unexpected git invocation before drift rejection: {args!r}")

    monkeypatch.setattr(ab, "_git", fake_git)
    with pytest.raises(ab.AbBaselineCandidateError, match="candidate pbr_v2 ref moved"):
        ab.inspect_candidate_authority(
            repo_root=ROOT,
            expected_main_revision=MAIN,
            expected_pbr_revision="e" * 40,
            expected_throughput_revision=THROUGHPUT,
        )
