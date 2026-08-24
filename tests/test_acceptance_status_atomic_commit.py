from pathlib import Path

import pytest

from bodyrig.acceptance_status import AcceptanceStatusError, GateAInfo, _platform_stage


def _gate(root: Path) -> GateAInfo:
    return GateAInfo(
        path=root / "bodyrig-acceptance.json",
        body_id="performer-123",
        revision="a" * 40,
        package_hash="1" * 64,
        runtime_hash="2" * 64,
    )


def test_absent_canonical_directory_means_platform_probe_is_pending(tmp_path: Path) -> None:
    stage, paths = _platform_stage(
        tmp_path,
        platform="windows-unity-univrm",
        prefix="windows",
        attestation_name="bodyrig-renderer-acceptance-windows.json",
        gate=_gate(tmp_path),
    )
    assert stage == "probe"
    assert paths.layout == "pending"
    assert paths.probe == tmp_path / "windows-evidence" / "windows-probe.json"


def test_empty_canonical_directory_is_not_treated_as_pending(tmp_path: Path) -> None:
    (tmp_path / "windows-evidence").mkdir()
    with pytest.raises(
        AcceptanceStatusError,
        match="canonical evidence directory exists without its committed machine/deformation pair",
    ):
        _platform_stage(
            tmp_path,
            platform="windows-unity-univrm",
            prefix="windows",
            attestation_name="bodyrig-renderer-acceptance-windows.json",
            gate=_gate(tmp_path),
        )
