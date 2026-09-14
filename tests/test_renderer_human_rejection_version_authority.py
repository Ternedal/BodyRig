from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import renderer_human_rejection as rejection


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
PLATFORM = "windows-unity-univrm"
REVISION = "a" * 40
BODY_ID = "body-test"
AUTOMATED_SHA = "b" * 64
PROBE_SHA = "c" * 64
DEFORMATION_SHA = "d" * 64
PACKAGE_SHA = "e" * 64
RUNTIME_SHA = "f" * 64


def _write_receipt(tmp_path: Path, version: Any) -> Path:
    rejection.write_rejection(
        tmp_path,
        platform=PLATFORM,
        bodyrig_revision=REVISION,
        body_id=BODY_ID,
        automated_report_sha256=AUTOMATED_SHA,
        probe_report_sha256=PROBE_SHA,
        deformation_report_sha256=DEFORMATION_SHA,
        package_sha256=PACKAGE_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        failed_checks=["hair_appearance"],
        quality_note="Visible source hair mismatch in renderer review.",
    )
    path = rejection.rejection_path(tmp_path, PLATFORM)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["version"] = version
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _read(tmp_path: Path) -> dict[str, Any]:
    return rejection.read_rejection(
        tmp_path,
        platform=PLATFORM,
        bodyrig_revision=REVISION,
        body_id=BODY_ID,
        automated_report_sha256=AUTOMATED_SHA,
        probe_report_sha256=PROBE_SHA,
        deformation_report_sha256=DEFORMATION_SHA,
        package_sha256=PACKAGE_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
    )


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_rejection_readback_rejects_boolean_non_numeric_and_wrong_v1(tmp_path: Path, version: Any) -> None:
    _write_receipt(tmp_path, version)

    with pytest.raises(
        rejection.RendererHumanRejectionError,
        match="renderer human rejection format/version/policy mismatch",
    ):
        _read(tmp_path)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_rejection_readback_preserves_numeric_v1_and_negative_authority(tmp_path: Path, version: Any) -> None:
    _write_receipt(tmp_path, version)

    value = _read(tmp_path)

    assert value["version"] == version
    assert value["failed_checks"] == ["hair_appearance"]
    assert value["human_review_pass"] is False
    assert value["production_activation"] is False
