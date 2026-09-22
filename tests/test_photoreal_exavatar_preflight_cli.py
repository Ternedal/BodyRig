from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_preflight_cli as cli


def _legacy_unreadable_receipt() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-exavatar-preflight",
        "version": 1,
        "strict_upstream_asset_inventory": True,
        "benchmark_environment_ready": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "blockers": sorted(
            f"dependency is not a readable git checkout: {relative}"
            for relative in cli.PUBLIC_TOOL_LAYOUT.values()
        ),
    }


def test_only_exact_unreadable_dependency_receipt_is_migratable(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(_legacy_unreadable_receipt()), encoding="utf-8")
    assert cli._is_migratable_unreadable_dependency_receipt(path) is True

    drifted = _legacy_unreadable_receipt()
    drifted["blockers"] = [*drifted["blockers"], "missing asset: unexpected.bin"]
    path.write_text(json.dumps(drifted), encoding="utf-8")
    assert cli._is_migratable_unreadable_dependency_receipt(path) is False


def test_reuse_existing_rebuilds_only_the_known_fail_closed_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "preflight.json"
    output.write_text(json.dumps(_legacy_unreadable_receipt()), encoding="utf-8")
    called: dict[str, object] = {}

    def fake_build(**kwargs):
        called.update(kwargs)
        Path(kwargs["output_path"]).write_text("{}\n", encoding="utf-8")
        return {
            "format": "bodyrig-photoreal-exavatar-preflight",
            "version": 1,
            "smplx_gender": "female",
            "benchmark_environment_ready": True,
            "blockers": [],
            "strict_upstream_asset_inventory": True,
            "automatic_restricted_asset_download": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }

    def fail_validate(*args, **kwargs):
        raise AssertionError("legacy unreadable-dependency receipt must be rebuilt, not strict-reused")

    monkeypatch.setattr(cli, "build_exavatar_preflight_strict_files", fake_build)
    monkeypatch.setattr(cli, "validate_exavatar_preflight_strict_file", fail_validate)

    code = cli.main(
        [
            "--dependency-root",
            str(tmp_path / "deps"),
            "--asset-root",
            str(tmp_path / "assets"),
            "--reference-model-root",
            str(tmp_path / "reference"),
            "--smplx-gender",
            "female",
            "--out",
            str(output),
            "--no-colmap",
            "--reuse-existing",
        ]
    )

    assert code == 0
    assert Path(called["output_path"]) == output.resolve()
    assert output.read_text(encoding="utf-8") == "{}\n"
