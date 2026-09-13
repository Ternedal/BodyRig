from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bodyrig.ui_jobs import UiJobError, _body_source_evidence, _bound_body_source, _read_job, _v1


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "clone-body-from-stash.ps1"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_ui_v1_runtime_semantics() -> None:
    assert _v1(1)
    assert _v1(1.0)
    for value in (True, False, "1", None, 2):
        assert not _v1(value)


@pytest.mark.parametrize("invalid_version", [True, "1", None])
def test_ui_job_state_rejects_non_numeric_v1(tmp_path: Path, invalid_version: object) -> None:
    path = tmp_path / "job.json"
    _write_json(path, {"format": "bodyrig-ui-job", "version": invalid_version})
    with pytest.raises(UiJobError, match="unsupported UI job state"):
        _read_job(path)


def test_ui_job_state_accepts_numeric_one_point_zero(tmp_path: Path) -> None:
    path = tmp_path / "job.json"
    _write_json(path, {"format": "bodyrig-ui-job", "version": 1.0})
    assert _read_job(path)["version"] == 1.0


@pytest.mark.parametrize("invalid_version", [True, "1", None])
def test_source_enqueue_authority_rejects_non_numeric_v1_before_profile_lookup(invalid_version: object) -> None:
    job = {
        "job_id": "job-test",
        "person_id": "person-test",
        "bodyrig_revision": "a" * 40,
        "source_enqueue_authority": {
            "format": "bodyrig-body-build-source-enqueue-authority",
            "version": invalid_version,
            "job_id": "job-test",
            "person_id": "person-test",
            "stash_performer_id": "42",
            "expected_bodyrig_revision": "a" * 40,
        },
    }
    with pytest.raises(UiJobError, match="source enqueue authority format/version mismatch"):
        _bound_body_source(job)


@pytest.mark.parametrize("invalid_version", [True, "1", None])
def test_post_build_source_manifest_rejects_non_numeric_v1(tmp_path: Path, invalid_version: object) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"exact-source-bytes")
    _write_json(
        tmp_path / "bodyrig-stash-source-manifest.json",
        {
            "format": "bodyrig-stash-source-manifest",
            "version": invalid_version,
            "source_kind": "stash-local",
            "performer": {"id": "42", "name": "Fixture"},
            "selected": [{"scene_id": "11", "path": str(source)}],
        },
    )
    with pytest.raises(UiJobError, match="source manifest format/version mismatch"):
        _body_source_evidence(str(tmp_path), performer_id="42")


def test_post_build_source_manifest_preserves_numeric_v1_and_byte_hashing(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"exact-source-bytes")
    _write_json(
        tmp_path / "bodyrig-stash-source-manifest.json",
        {
            "format": "bodyrig-stash-source-manifest",
            "version": 1.0,
            "source_kind": "stash-local",
            "performer": {"id": "42", "name": "Fixture"},
            "selected": [{"scene_id": "11", "path": str(source)}],
        },
    )
    _, files = _body_source_evidence(str(tmp_path), performer_id="42")
    assert files[0]["scene_id"] == "11"
    assert files[0]["name"] == "clip.mp4"
    assert len(files[0]["sha256"]) == 64


def test_stash_launcher_uses_bool_safe_v1_at_source_points_of_use() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    assert "Test-V1Version $manifest.version" in source
    assert "Test-V1Version $segmentManifest.version" in source
    assert "[int]$segmentManifest.version" not in source

    manifest_read = source.index("$manifest = Get-Content -LiteralPath $sourceManifest")
    manifest_version = source.index("Test-V1Version $manifest.version", manifest_read)
    performer_use = source.index("$manifest.performer.id", manifest_read)
    assert manifest_read < manifest_version < performer_use

    segment_read = source.index("$segmentManifest = Get-Content -LiteralPath $observationSegments")
    segment_version = source.index("Test-V1Version $segmentManifest.version", segment_read)
    clone_args = source.index('$cloneArgs = @(', segment_read)
    assert segment_read < segment_version < clone_args


def test_stash_launcher_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    launcher = str(LAUNCHER.resolve()).replace("'", "''")
    script = rf"""
+$tokens = $null
+$errors = $null
+$ast = [System.Management.Automation.Language.Parser]::ParseFile('{launcher}', [ref]$tokens, [ref]$errors)
+if ($errors.Count -ne 0) {{ exit 20 }}
+$fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-V1Version' }}, $true)
+if ($null -eq $fn) {{ exit 21 }}
+Invoke-Expression $fn.Extent.Text
+if (-not (Test-V1Version 1)) {{ exit 31 }}
+if (-not (Test-V1Version 1.0)) {{ exit 32 }}
+if (Test-V1Version $true) {{ exit 33 }}
+if (Test-V1Version $false) {{ exit 34 }}
+if (Test-V1Version '1') {{ exit 35 }}
+if (Test-V1Version $null) {{ exit 36 }}
+if (Test-V1Version 2) {{ exit 37 }}
+exit 0
+"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
