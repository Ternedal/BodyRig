from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_source_alignment import file_sha256
from bodyrig.ui_jobs import UiJobError, _body_source_evidence


def _manifest(root: Path, source: Path, *, performer_id: str = "42") -> Path:
    path = root / "bodyrig-stash-source-manifest.json"
    path.write_text(
        json.dumps(
            {
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "source_kind": "stash-local",
                "performer": {"id": performer_id, "name": "Lauren Phillips", "disambiguation": ""},
                "stash_version": "fixture",
                "candidate_count": 1,
                "selected": [
                    {
                        "scene_id": "11",
                        "scene_title": "Fixture",
                        "path": str(source),
                        "width": 1920,
                        "height": 1080,
                        "duration": 30,
                        "framerate": 30,
                        "performer_count": 1,
                        "score": 100,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_body_source_evidence_hashes_exact_selected_bytes(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"exact-stash-source-bytes")
    manifest = _manifest(tmp_path, source)

    resolved_manifest, files = _body_source_evidence(str(tmp_path), performer_id="42")

    assert resolved_manifest == manifest.resolve()
    assert files == [
        {
            "scene_id": "11",
            "name": "clip.mp4",
            "sha256": file_sha256(source),
        }
    ]
    assert "tmp" not in json.dumps(files).lower()


def test_body_source_evidence_rejects_wrong_performer(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    _manifest(tmp_path, source, performer_id="99")

    with pytest.raises(UiJobError, match="performer"):
        _body_source_evidence(str(tmp_path), performer_id="42")


def test_body_source_evidence_rejects_missing_source_bytes(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"
    _manifest(tmp_path, missing)

    with pytest.raises(UiJobError, match="no longer readable"):
        _body_source_evidence(str(tmp_path), performer_id="42")
