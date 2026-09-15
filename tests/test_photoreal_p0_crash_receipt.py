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
    read_p0_crash_receipt,
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
        child_exit_code=137,
        error_message="P0 child exited unexpectedly with code 137.",
        output_root=root,
    )
    validated = validate_p0_crash_receipt(receipt)

    assert validated["child_exit_code"] == 137
    assert validated["artifact_present_count"] == 5
    assert validated["artifact_expected_count"] == len(P0_OUTPUTS)
    assert validated["artifact_presence"][P0_OUTPUTS[0]] is True
    assert validated["artifact_presence"][P0_OUTPUTS[5]] is False
    assert validated["partial_outputs_may_not_grant_authority"] is True
    assert validated["restart_same_output_root_supported"] is False
    assert validated["teacher_training_authorized"] is False
    assert validated["photoreal_acceptance_authority"] is False
    assert validated["production_activation"] is False


def test_crash_receipt_persists_and_reads_back_structured_windows_exit_code(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    for relative in P0_OUTPUTS[:3]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    receipt = build_p0_crash_receipt(
        bodyrig_revision="b" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        child_exit_code=-1073741819,
        error_message="unexpected child failure",
        output_root=root,
    )
    output = tmp_path / "receipt.json"
    write_p0_crash_receipt(receipt, output)
    loaded = read_p0_crash_receipt(output)
    assert loaded["child_exit_code"] == -1073741819
    assert loaded["artifact_present_count"] == 3
    assert loaded["p0_crash_receipt_sha256"] == receipt["p0_crash_receipt_sha256"]


def test_crash_receipt_is_create_only(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    receipt = build_p0_crash_receipt(
        bodyrig_revision="c" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        child_exit_code=1,
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
        bodyrig_revision="d" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        child_exit_code=1,
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
        bodyrig_revision="e" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        child_exit_code=1,
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
        bodyrig_revision="f" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        child_exit_code=1,
        error_message="unexpected child failure",
        output_root=root,
    )
    receipt["artifact_present_count"] = 1
    receipt["p0_crash_receipt_sha256"] = _digest(receipt)
    with pytest.raises(PhotorealP0CrashReceiptError, match="present count mismatch"):
        validate_p0_crash_receipt(receipt)


@pytest.mark.parametrize("invalid_exit_code", [True, 0, 2])
def test_crash_receipt_rejects_non_unexpected_child_exit_codes(
    tmp_path: Path, invalid_exit_code: object
) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    with pytest.raises(PhotorealP0CrashReceiptError, match="child exit code"):
        build_p0_crash_receipt(
            bodyrig_revision="1" * 40,
            performer_id="42",
            failed_stage_number=0,
            failed_stage_label="isolated-p0-child-process",
            child_exit_code=invalid_exit_code,  # type: ignore[arg-type]
            error_message="unexpected child failure",
            output_root=root,
        )


def test_crash_receipt_rejects_resealed_reserved_child_exit_code(tmp_path: Path) -> None:
    root = tmp_path / "p0"
    root.mkdir()
    receipt = build_p0_crash_receipt(
        bodyrig_revision="2" * 40,
        performer_id="42",
        failed_stage_number=0,
        failed_stage_label="isolated-p0-child-process",
        child_exit_code=1,
        error_message="unexpected child failure",
        output_root=root,
    )
    receipt["child_exit_code"] = 2
    receipt["p0_crash_receipt_sha256"] = _digest(receipt)
    with pytest.raises(PhotorealP0CrashReceiptError, match="unexpected P0 failure"):
        validate_p0_crash_receipt(receipt)
