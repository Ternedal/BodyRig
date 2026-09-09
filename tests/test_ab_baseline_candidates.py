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


def _install_inspection_git(monkeypatch, contract: dict, normalized: dict) -> None:
    revision_by_name = {"pbr_v3": PBR, "recovery_throughput_v3": THROUGHPUT}
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
            name = "pbr_v3" if revision == PBR else "recovery_throughput_v3"
            return "\n".join(normalized[name]["files"])
        raise AssertionError(f"unexpected git invocation: {args!r}")

    monkeypatch.setattr(ab, "_git", fake_git)


def _reviewed_base_for_path(normalized: dict, path: str) -> str | None:
    matches = [candidate["base_files"][path] for candidate in normalized.values() if path in candidate["base_files"]]
    assert len(matches) == 1
    return matches[0]


def _install_exact_tree_blobs(monkeypatch, normalized: dict) -> None:
    monkeypatch.setattr(
        ab,
        "_tree_blob_or_none",
        lambda _repo, revision, path: _reviewed_base_for_path(normalized, path) if revision == MAIN else None,
    )

    def fake_tree_blob(_repo: Path, revision: str, path: str) -> str:
        name = "pbr_v3" if revision == PBR else "recovery_throughput_v3"
        return normalized[name]["files"][path]

    monkeypatch.setattr(ab, "_tree_blob", fake_tree_blob)


def test_reviewed_contract_binds_every_active_candidate_and_base_blob() -> None:
    value = _contract()
    normalized = ab._validate_contract(value)

    assert set(normalized) == {"pbr_v3", "recovery_throughput_v3"}
    assert len(normalized["pbr_v3"]["files"]) == 3
    assert len(normalized["pbr_v3"]["base_files"]) == 3
    assert len(normalized["recovery_throughput_v3"]["files"]) == 18
    assert len(normalized["recovery_throughput_v3"]["base_files"]) == 18
    assert normalized["pbr_v3"]["ref"] == "candidate/skin-pbr-v3-linear-light-20260909"
    assert normalized["pbr_v3"]["base_files"]["bodyrig/bridges/sith_pbr_material.py"] == (
        "c2505f3399ec08110f05c46235af8ade4aefa030"
    )
    assert normalized["pbr_v3"]["files"]["bodyrig/bridges/sith_pbr_material.py"] == (
        "b7c3df91d65cab41ed9b3ed3123b21bb2ac8f7be"
    )
    assert normalized["pbr_v3"]["files"]["tests/test_sith_basecolor_detail.py"] == (
        "be8ee63187efd595c1e80902d0002bb155f09e21"
    )
    assert normalized["pbr_v3"]["files"]["tests/test_sith_pbr_material.py"] == (
        "085052f1a01818ab23fd01f628ce74bc484d7d56"
    )
    assert normalized["recovery_throughput_v3"]["base_files"]["bodyrig/bridges/hmr2_checkpoint_bridge.py"] == (
        "1ef739b7177ca30aa7fafc131bd45e3ff6d45d2f"
    )
    assert normalized["recovery_throughput_v3"]["base_files"]["bodyrig/recovery_throughput_human_review.py"] is None
    assert normalized["recovery_throughput_v3"]["files"]["bodyrig/bridges/hmr2_checkpoint_bridge.py"] == (
        "853414c46568cfeb8d00fbb00c51acf491d78dbd"
    )
    assert normalized["recovery_throughput_v3"]["files"]["bodyrig/bridges/hmr2_config.py"] == (
        "d310d972b25edec83552babfd2e7e0626698be3e"
    )
    assert normalized["recovery_throughput_v3"]["files"]["bodyrig/bridges/hmr2_resume_bridge.py"] == (
        "d8ddd983cc9a6275d424add81ed530326cdf9c0a"
    )


def test_contract_cannot_grant_physical_promotion_or_production_authority() -> None:
    value = _contract()
    value["production_activation"] = True
    with pytest.raises(ab.AbBaselineCandidateError, match="cannot grant physical, promotion or production authority"):
        ab._validate_contract(value)

    value = _contract()
    value["promotion_authority"] = True
    with pytest.raises(ab.AbBaselineCandidateError, match="cannot grant physical, promotion or production authority"):
        ab._validate_contract(value)


def test_contract_rejects_unknown_top_level_authority_field() -> None:
    value = _contract()
    value["implicit_acceptance"] = True
    with pytest.raises(ab.AbBaselineCandidateError, match="unexpected top-level fields"):
        ab._validate_contract(value)


def test_contract_rejects_unreviewed_candidate_or_unsafe_ref() -> None:
    value = _contract()
    value["candidates"]["surprise"] = copy.deepcopy(value["candidates"]["pbr_v3"])
    with pytest.raises(ab.AbBaselineCandidateError, match="exactly the PBR v3 and throughput v3"):
        ab._validate_contract(value)

    value = _contract()
    value["candidates"]["pbr_v3"]["ref"] = "candidate/../wrong"
    with pytest.raises(ab.AbBaselineCandidateError, match="safe candidate branch ref"):
        ab._validate_contract(value)


def test_contract_rejects_superseded_pbr_v2_authority_key() -> None:
    value = _contract()
    value["candidates"]["pbr_v2"] = value["candidates"].pop("pbr_v3")
    with pytest.raises(ab.AbBaselineCandidateError, match="exactly the PBR v3 and throughput v3"):
        ab._validate_contract(value)


def test_contract_requires_exact_reviewed_base_path_set() -> None:
    value = _contract()
    value["candidates"]["pbr_v3"]["base_files"].pop("tests/test_sith_pbr_material.py")
    with pytest.raises(ab.AbBaselineCandidateError, match="base_files must exactly match"):
        ab._validate_contract(value)

    value = _contract()
    value["candidates"]["pbr_v3"]["base_files"]["unexpected.py"] = None
    with pytest.raises(ab.AbBaselineCandidateError, match="base_files must exactly match"):
        ab._validate_contract(value)


def test_contract_rejects_invalid_reviewed_base_blob_but_allows_explicit_absence() -> None:
    value = _contract()
    assert value["candidates"]["recovery_throughput_v3"]["base_files"]["compare-recovery-throughput.ps1"] is None
    ab._validate_contract(value)

    value = _contract()
    value["candidates"]["pbr_v3"]["base_files"]["bodyrig/bridges/sith_pbr_material.py"] = "not-a-blob"
    with pytest.raises(ab.AbBaselineCandidateError, match="base blob.*exact Git revision"):
        ab._validate_contract(value)


def test_inspection_requires_clean_exact_main_and_one_commit_candidate_deltas(monkeypatch) -> None:
    contract = _contract()
    normalized = ab._validate_contract(contract)
    _install_inspection_git(monkeypatch, contract, normalized)
    _install_exact_tree_blobs(monkeypatch, normalized)

    result = ab.inspect_candidate_authority(repo_root=ROOT)
    assert result["main_revision"] == MAIN
    assert result["candidates"]["pbr_v3"]["revision"] == PBR
    assert result["candidates"]["recovery_throughput_v3"]["revision"] == THROUGHPUT
    assert result["comparison_only"] is True
    assert result["physical_acceptance_authority"] is False
    assert result["promotion_authority"] is False
    assert result["production_activation"] is False


def test_inspection_rejects_existing_main_blob_drift_even_when_candidate_blob_is_exact(monkeypatch) -> None:
    contract = _contract()
    normalized = ab._validate_contract(contract)
    _install_inspection_git(monkeypatch, contract, normalized)

    drift_path = "bodyrig/bridges/sith_pbr_material.py"

    def fake_base(_repo: Path, revision: str, path: str) -> str | None:
        assert revision == MAIN
        if path == drift_path:
            return "f" * 40
        return _reviewed_base_for_path(normalized, path)

    monkeypatch.setattr(ab, "_tree_blob_or_none", fake_base)

    def exact_candidate_blob(_repo: Path, revision: str, path: str) -> str:
        name = "pbr_v3" if revision == PBR else "recovery_throughput_v3"
        return normalized[name]["files"][path]

    monkeypatch.setattr(ab, "_tree_blob", exact_candidate_blob)

    with pytest.raises(ab.AbBaselineCandidateError, match="pbr_v3 reviewed base state drifted.*sith_pbr_material.py"):
        ab.inspect_candidate_authority(repo_root=ROOT)


def test_inspection_rejects_new_main_file_where_reviewed_base_was_absent(monkeypatch) -> None:
    contract = _contract()
    normalized = ab._validate_contract(contract)
    _install_inspection_git(monkeypatch, contract, normalized)

    appeared_path = "bodyrig/recovery_throughput_human_review.py"

    def fake_base(_repo: Path, revision: str, path: str) -> str | None:
        assert revision == MAIN
        if path == appeared_path:
            return "f" * 40
        return _reviewed_base_for_path(normalized, path)

    monkeypatch.setattr(ab, "_tree_blob_or_none", fake_base)

    def exact_candidate_blob(_repo: Path, revision: str, path: str) -> str:
        name = "pbr_v3" if revision == PBR else "recovery_throughput_v3"
        return normalized[name]["files"][path]

    monkeypatch.setattr(ab, "_tree_blob", exact_candidate_blob)

    with pytest.raises(
        ab.AbBaselineCandidateError,
        match="recovery_throughput_v3 reviewed base state drifted.*recovery_throughput_human_review.py",
    ):
        ab.inspect_candidate_authority(repo_root=ROOT)


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
        if args == ("rev-parse", f"refs/remotes/origin/{normalized['pbr_v3']['ref']}"):
            return PBR
        if args == ("rev-parse", f"refs/remotes/origin/{normalized['recovery_throughput_v3']['ref']}"):
            return THROUGHPUT
        raise AssertionError(f"unexpected git invocation before drift rejection: {args!r}")

    monkeypatch.setattr(ab, "_git", fake_git)
    with pytest.raises(ab.AbBaselineCandidateError, match="candidate pbr_v3 ref moved"):
        ab.inspect_candidate_authority(
            repo_root=ROOT,
            expected_main_revision=MAIN,
            expected_pbr_revision="e" * 40,
            expected_throughput_revision=THROUGHPUT,
        )
