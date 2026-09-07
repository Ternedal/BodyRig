from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.renderer_human_rejection import (
    RendererHumanRejectionError,
    read_rejection,
    rejection_path,
    write_rejection,
)

REVISION = "a" * 40
BODY_ID = "lauren-phillips-test-01"
GATE = "1" * 64
PROBE = "2" * 64
DEFORMATION = "3" * 64
PACKAGE = "4" * 64
RUNTIME = "5" * 64
PLATFORM = "windows-unity-univrm"


def _kwargs() -> dict[str, object]:
    return {
        "platform": PLATFORM,
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "automated_report_sha256": GATE,
        "probe_report_sha256": PROBE,
        "deformation_report_sha256": DEFORMATION,
        "package_sha256": PACKAGE,
        "runtime_manifest_sha256": RUNTIME,
    }


def test_rejection_is_create_only_and_hash_bound(tmp_path: Path) -> None:
    receipt = write_rejection(
        tmp_path,
        **_kwargs(),
        failed_checks=["source_identity", "skin_appearance", "hair_appearance"],
        quality_note="Face does not match source; skin is incomplete and hair is missing.",
    )
    path = rejection_path(tmp_path, PLATFORM)
    assert Path(str(receipt["rejection_path"])) == path
    assert receipt["human_review_pass"] is False
    assert receipt["production_activation"] is False
    assert receipt["failed_checks"] == ["hair_appearance", "skin_appearance", "source_identity"]

    read = read_rejection(tmp_path, **_kwargs())
    assert read["body_id"] == BODY_ID
    assert read["package_sha256"] == PACKAGE

    with pytest.raises(RendererHumanRejectionError, match="refusing to overwrite"):
        write_rejection(
            tmp_path,
            **_kwargs(),
            failed_checks=["geometry_proportions"],
            quality_note="Different rejection must not overwrite prior operator evidence.",
        )


def test_rejection_requires_real_failure_and_note(tmp_path: Path) -> None:
    with pytest.raises(RendererHumanRejectionError, match="at least one"):
        write_rejection(tmp_path, **_kwargs(), failed_checks=[], quality_note="Observed failure")
    with pytest.raises(RendererHumanRejectionError, match="placeholder"):
        write_rejection(
            tmp_path,
            **_kwargs(),
            failed_checks=["source_identity"],
            quality_note="<describe failure>",
        )


def test_rejection_fails_closed_after_evidence_binding_tamper(tmp_path: Path) -> None:
    write_rejection(
        tmp_path,
        **_kwargs(),
        failed_checks=["geometry_proportions", "eye_appearance"],
        quality_note="Body proportions and eyes are not faithful to source.",
    )
    with pytest.raises(RendererHumanRejectionError, match="probe_report_sha256"):
        read_rejection(tmp_path, **{**_kwargs(), "probe_report_sha256": "9" * 64})


def test_rejection_rejects_noncanonical_failed_check_bytes(tmp_path: Path) -> None:
    write_rejection(
        tmp_path,
        **_kwargs(),
        failed_checks=["skin_appearance"],
        quality_note="Skin is visibly incomplete.",
    )
    path = rejection_path(tmp_path, PLATFORM)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["failed_checks"] = ["skin_appearance", "skin_appearance"]
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(RendererHumanRejectionError, match="failed_checks"):
        read_rejection(tmp_path, **_kwargs())


def test_operator_wrapper_requires_explicit_rejection_confirmation() -> None:
    source = Path("record-renderer-rejection.ps1").read_text(encoding="utf-8")
    assert "[switch]$ConfirmRejection" in source
    assert "bodyrig.renderer_human_rejection_cli" in source
    assert "human_review_pass -ne $false" in source
    assert "production_activation -ne $false" in source
    assert "record-renderer-acceptance.ps1" not in source
