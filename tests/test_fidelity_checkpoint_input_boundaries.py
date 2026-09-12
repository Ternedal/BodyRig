from __future__ import annotations

import json

import pytest

from bodyrig.fidelity_checkpoint import (
    FidelityCheckpointError,
    _number,
    _strict_policy,
    validate_checkpoint,
)


POLICY = {
    "max_full_rebuilds": 2,
    "max_refinements_per_rebuild": 3,
    "max_wall_clock_hours": 8.0,
    "base_sith_seed": 1337,
    "reference_limit": 24,
}


def _checkpoint_prefix(
    *,
    version: object = 1,
    active_elapsed_seconds: object = 1.0,
    sequence: object = 1,
) -> dict[str, object]:
    return {
        "format": "bodyrig-fidelity-convergence-checkpoint",
        "version": version,
        "sequence": sequence,
        "stage": "post-reconstruction",
        "bodyrig_revision": "1" * 40,
        "performer_id": "42",
        "body_alias": "fixture",
        "policy": dict(POLICY),
        "rig_setup_sha256": "2" * 64,
        "active_elapsed_seconds": active_elapsed_seconds,
        "state": {},
        "artifacts": [],
        "human_visual_authority_required": True,
        "production_activation": False,
    }


def test_number_huge_integer_fails_with_checkpoint_error() -> None:
    with pytest.raises(FidelityCheckpointError, match="probe is invalid"):
        _number(10**400, field="probe")


def test_checkpoint_rejects_boolean_version_constant() -> None:
    with pytest.raises(FidelityCheckpointError, match="format/version"):
        validate_checkpoint(_checkpoint_prefix(version=True))


def test_checkpoint_preserves_numeric_version_equality() -> None:
    with pytest.raises(FidelityCheckpointError, match="sequence is invalid"):
        validate_checkpoint(_checkpoint_prefix(version=1.0, sequence=None))


def test_checkpoint_huge_active_elapsed_fails_with_domain_error() -> None:
    with pytest.raises(FidelityCheckpointError, match="active_elapsed_seconds is invalid"):
        validate_checkpoint(_checkpoint_prefix(active_elapsed_seconds=10**400))


def test_policy_json_huge_wall_clock_fails_with_domain_error() -> None:
    policy = dict(POLICY)
    policy["max_wall_clock_hours"] = 10**400

    with pytest.raises(FidelityCheckpointError, match="policy.max_wall_clock_hours is invalid"):
        _strict_policy(json.dumps(policy))
