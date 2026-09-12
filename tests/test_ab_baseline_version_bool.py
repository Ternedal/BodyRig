from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.ab_baseline_candidates as ab


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "ab-baseline-candidates-v1.json"
CYCLE_STATE_PATH = ROOT / "contracts" / "ab-baseline-cycle-state-v1.json"


def _contract(version: object) -> dict[str, object]:
    value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    value["version"] = version
    return value


def _cycle_state(version: object) -> dict[str, object]:
    value = json.loads(CYCLE_STATE_PATH.read_text(encoding="utf-8"))
    value["version"] = version
    return value


def _write_cycle_state(repo: Path, value: dict[str, object]) -> None:
    path = repo / ab.CYCLE_STATE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_candidate_contract_rejects_boolean_v1_version() -> None:
    with pytest.raises(ab.AbBaselineCandidateError, match="candidate contract format/version mismatch"):
        ab._validate_contract(_contract(True))


def test_candidate_contract_accepts_numeric_float_v1_without_authority_expansion() -> None:
    normalized = ab._validate_contract(_contract(1.0))

    assert set(normalized) == {"pbr_v3", "recovery_throughput_v3"}
    assert all(candidate["files"] for candidate in normalized.values())
    assert all(set(candidate["base_files"]) == set(candidate["files"]) for candidate in normalized.values())


def test_archived_cycle_state_rejects_boolean_v1_version(tmp_path: Path) -> None:
    _write_cycle_state(tmp_path, _cycle_state(True))

    with pytest.raises(ab.AbBaselineCandidateError, match="lifecycle state format/version mismatch"):
        ab._assert_cycle_open(tmp_path)


def test_archived_cycle_state_accepts_numeric_float_v1_but_remains_closed(monkeypatch, tmp_path: Path) -> None:
    _write_cycle_state(tmp_path, _cycle_state(1.0))
    monkeypatch.setattr(
        ab,
        "_tree_blob",
        lambda _repo, revision, path: (
            ab.HISTORICAL_V1_CONTRACT_GIT_BLOB
            if revision == "HEAD" and path == ab.CONTRACT_RELATIVE_PATH.as_posix()
            else (_ for _ in ()).throw(AssertionError((revision, path)))
        ),
    )

    with pytest.raises(ab.AbBaselineCandidateError, match="completed/promoted and archived"):
        ab._assert_cycle_open(tmp_path)
