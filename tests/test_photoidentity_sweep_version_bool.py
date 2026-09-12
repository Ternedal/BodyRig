from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoidentity_sweep as sweep


PERFORMER_ID = "performer-1"
BODYRIG_REVISION = "a" * 40


def _inputs(tmp_path: Path, *, version: object) -> tuple[Path, Path, bytes]:
    manifest = tmp_path / "bodyrig-stash-source-manifest.json"
    raw = json.dumps(
        {
            "format": "bodyrig-stash-source-manifest",
            "version": version,
            "performer": {"id": PERFORMER_ID},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest.write_bytes(raw)
    config = tmp_path / "analyzer.json"
    config.write_text("{}", encoding="utf-8")
    return manifest, config, raw


def _run(manifest: Path, config: Path, output: Path) -> dict[str, object]:
    return sweep.run_sweep(
        performer_id=PERFORMER_ID,
        baseline_source_manifest=manifest,
        analyzer_config_path=config,
        stash_url="http://stash.test",
        stash_api_key="secret",
        bodyrig_revision=BODYRIG_REVISION,
        output_dir=output,
        ffmpeg="ffmpeg",
    )


def test_boolean_baseline_manifest_version_fails_before_analyzer_config(monkeypatch, tmp_path: Path) -> None:
    manifest, config, _raw = _inputs(tmp_path, version=True)

    def unexpected_config(_path: Path) -> dict[str, object]:
        raise AssertionError("boolean baseline version crossed the manifest trust boundary")

    monkeypatch.setattr(sweep, "_load_config", unexpected_config)

    with pytest.raises(sweep.PhotoIdentitySweepError, match="baseline Stash source manifest format/version is invalid"):
        _run(manifest, config, tmp_path / "out")


@pytest.mark.parametrize("version", [1, 1.0], ids=["int-v1", "float-v1"])
def test_numeric_v1_baseline_manifest_preserves_exact_byte_hash(monkeypatch, tmp_path: Path, version: object) -> None:
    manifest, config, raw = _inputs(tmp_path, version=version)
    observed_hashes: list[tuple[Path, str]] = []
    original_sha256 = sweep._sha256

    def capture_sha256(path: Path) -> str:
        digest = original_sha256(path)
        observed_hashes.append((path, digest))
        return digest

    monkeypatch.setattr(sweep, "_sha256", capture_sha256)
    monkeypatch.setattr(
        sweep,
        "_load_config",
        lambda _path: {
            "adapter": "test-adapter",
            "revision": "1",
            "command": ["analyzer", "--bodyrig-stash-manifest", "placeholder.json"],
            "timeout_seconds": 1,
        },
    )

    class StopAfterBaseline(Exception):
        pass

    def stop_before_external_stash(_config: object) -> object:
        raise StopAfterBaseline

    monkeypatch.setattr(sweep, "StashClient", stop_before_external_stash)

    with pytest.raises(StopAfterBaseline):
        _run(manifest, config, tmp_path / "out")

    assert observed_hashes == [(manifest.resolve(), hashlib.sha256(raw).hexdigest())]
