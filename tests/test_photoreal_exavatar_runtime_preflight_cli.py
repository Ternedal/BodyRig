from __future__ import annotations

from pathlib import Path

from bodyrig import photoreal_exavatar_runtime_preflight_cli as cli


def _result() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-exavatar-runtime-preflight",
        "version": 1,
        "python_version": "3.10.12",
        "runtime_setup_provenance_verified": True,
        "runtime_setup_sha256": "a" * 64,
        "hand4whole_assets_sha256": "b" * 64,
        "runtime_environment_ready": True,
        "blockers": [],
        "cuda": {},
        "pytorch3d_cuda_smoke_passed": True,
        "gaussian_rasterizer": {"cuda_extension_available": True},
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_replace_existing_runtime_receipt_swaps_atomically(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "runtime-preflight.json"
    output.write_text("old\n", encoding="utf-8")
    called: dict[str, Path] = {}

    def fake_build(*, workspace_root, output_path):
        replacement = Path(output_path)
        called["replacement"] = replacement
        assert replacement != output
        assert output.read_text(encoding="utf-8") == "old\n"
        replacement.write_text("new\n", encoding="utf-8")
        return _result()

    monkeypatch.setattr(cli, "build_runtime_preflight_strict_file", fake_build)

    code = cli.main(
        [
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--out",
            str(output),
            "--replace-existing",
        ]
    )

    assert code == 0
    assert output.read_text(encoding="utf-8") == "new\n"
    assert called["replacement"].parent == output.parent
    assert called["replacement"].name.startswith(f".{output.name}.rebuild-")
    assert not called["replacement"].exists()


def test_replace_existing_runtime_receipt_preserves_old_on_rebuild_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "runtime-preflight.json"
    output.write_text("old\n", encoding="utf-8")
    seen: dict[str, Path] = {}

    def fail_build(*, workspace_root, output_path):
        replacement = Path(output_path)
        seen["replacement"] = replacement
        replacement.write_text("partial\n", encoding="utf-8")
        raise cli.PhotorealExAvatarRuntimePreflightStrictError("synthetic failure")

    monkeypatch.setattr(cli, "build_runtime_preflight_strict_file", fail_build)

    code = cli.main(
        [
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--out",
            str(output),
            "--replace-existing",
        ]
    )

    assert code == 1
    assert output.read_text(encoding="utf-8") == "old\n"
    assert not seen["replacement"].exists()
