from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_p0_crash_receipt import (
    P0_OUTPUTS,
    PhotorealP0CrashReceiptError,
    build_p0_crash_receipt,
    validate_p0_crash_receipt,
    write_p0_crash_receipt,
)


def _digest(value: dict[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "p0_crash_receipt_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def test_crash_receipt_records_partial_outputs_without_granting_authority(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    for relative in P0_OUTPUTS[:5]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    receipt = build_p0_crash_receipt(
        bodyrig_revision="a" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        error_message="P0 child exited unexpectedly with code 1.",
        output_root=root,
    )
    validated = validate_p0_crash_receipt(receipt)

    assert validated["artifact_present_count"] == 5
    assert validated["artifact_expected_count"] == len(P0_OUTPUTS)
    assert validated["artifact_presence"][P0_OUTPUTS[0]] is True
    assert validated["artifact_presence"][P0_OUTPUTS[5]] is False
    assert validated["partial_outputs_may_not_grant_authority"] is True
    assert validated["restart_same_output_root_supported"] is False
    assert validated["teacher_training_authorized"] is False
    assert validated["photoreal_acceptance_authority"] is False
    assert validated["production_activation"] is False


def test_crash_receipt_is_create_only(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    receipt = build_p0_crash_receipt(
        bodyrig_revision="b" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        error_message="unexpected child failure",
        output_root=root,
    )
    output = tmp_path / "receipt.json"
    write_p0_crash_receipt(receipt, output)
    with pytest.raises(PhotorealP0CrashReceiptError, match="already exists"):
        write_p0_crash_receipt(receipt, output)


def test_crash_receipt_rejects_boolean_version_even_when_resealed(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    receipt = build_p0_crash_receipt(
        bodyrig_revision="c" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        error_message="unexpected child failure",
        output_root=root,
    )
    receipt["version"] = True
    receipt["p0_crash_receipt_sha256"] = _digest(receipt)
    with pytest.raises(PhotorealP0CrashReceiptError, match="numeric v1"):
        validate_p0_crash_receipt(receipt)


def test_crash_receipt_rejects_resealed_authority_escalation(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    receipt = build_p0_crash_receipt(
        bodyrig_revision="d" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        error_message="unexpected child failure",
        output_root=root,
    )
    tampered = copy.deepcopy(receipt)
    tampered["teacher_training_authorized"] = True
    tampered["p0_crash_receipt_sha256"] = _digest(tampered)
    with pytest.raises(PhotorealP0CrashReceiptError, match="crossed authority boundary"):
        validate_p0_crash_receipt(tampered)


def test_crash_receipt_rejects_resealed_artifact_count_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    receipt = build_p0_crash_receipt(
        bodyrig_revision="e" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        error_message="unexpected child failure",
        output_root=root,
    )
    receipt["artifact_present_count"] = 1
    receipt["p0_crash_receipt_sha256"] = _digest(receipt)
    with pytest.raises(PhotorealP0CrashReceiptError, match="present count mismatch"):
        validate_p0_crash_receipt(receipt)
