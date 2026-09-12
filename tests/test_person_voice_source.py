from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.person_profiles import add_body_revision, create_profile, load_profile
from bodyrig.person_source_alignment import binding_path, file_sha256, write_binding
from bodyrig.person_voice_source import PersonVoiceSourceError, source_files_for_body


def _fixture(root: Path) -> tuple[dict, Path, Path]:
    media = root / "scene.mp4"
    media.write_bytes(b"exact-source-video")
    manifest = root / "bodyrig-stash-source-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "source_kind": "stash-local",
                "performer": {"id": "42", "name": "Source Fixture", "disambiguation": ""},
                "stash_version": "v-test",
                "candidate_count": 1,
                "selected": [
                    {
                        "scene_id": "scene-7",
                        "scene_title": "Fixture",
                        "path": str(media),
                        "width": 1920,
                        "height": 1080,
                        "duration": 30.0,
                        "framerate": 30.0,
                        "performer_count": 1,
                        "score": 100.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = create_profile(
        root,
        display_name="Source Fixture",
        stash_performer={"id": "42", "name": "Source Fixture", "disambiguation": ""},
    )
    profile = add_body_revision(
        root,
        profile["person_id"],
        body_id="fixture-body",
        package_sha256="a" * 64,
        package_path=str(root / "fixture.mrbody"),
    )
    write_binding(
        root,
        profile,
        kind="body",
        revision_id="body-r0001",
        evidence_kind="stash-physical-source-manifest-v1",
        evidence_sha256=file_sha256(manifest),
        evidence_ref=str(manifest),
        source_files=[{"scene_id": "scene-7", "name": media.name, "sha256": file_sha256(media)}],
    )
    return load_profile(root, profile["person_id"]), manifest, media


def _rewrite_manifest_version(root: Path, profile: dict, manifest: Path, version: object) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["version"] = version
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    path = binding_path(root, profile["person_id"], "body", "body-r0001")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["evidence"]["sha256"] = file_sha256(manifest)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_source_voice_files_revalidate_manifest_and_exact_media_bytes(tmp_path: Path) -> None:
    profile, manifest, media = _fixture(tmp_path)
    evidence = source_files_for_body(tmp_path, profile, body_revision="body-r0001")

    assert evidence["manifest_path"] == str(manifest.resolve())
    assert evidence["manifest_sha256"] == file_sha256(manifest)
    assert evidence["source_files"] == [
        {
            "scene_id": "scene-7",
            "name": media.name,
            "sha256": file_sha256(media),
            "path": str(media.resolve()),
        }
    ]


def test_source_voice_files_fail_closed_when_media_changes(tmp_path: Path) -> None:
    profile, _, media = _fixture(tmp_path)
    media.write_bytes(b"tampered-after-body-build")

    with pytest.raises(PersonVoiceSourceError, match="bytes no longer match"):
        source_files_for_body(tmp_path, profile, body_revision="body-r0001")


def test_source_voice_files_fail_closed_when_manifest_changes(tmp_path: Path) -> None:
    profile, manifest, _ = _fixture(tmp_path)
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(PersonVoiceSourceError, match="manifest no longer matches"):
        source_files_for_body(tmp_path, profile, body_revision="body-r0001")


def test_source_voice_files_reject_boolean_manifest_version_after_exact_rebind(tmp_path: Path) -> None:
    profile, manifest, _ = _fixture(tmp_path)
    _rewrite_manifest_version(tmp_path, profile, manifest, True)

    with pytest.raises(PersonVoiceSourceError, match="format/version mismatch"):
        source_files_for_body(tmp_path, profile, body_revision="body-r0001")


def test_source_voice_files_accept_numeric_float_manifest_version_after_exact_rebind(tmp_path: Path) -> None:
    profile, manifest, media = _fixture(tmp_path)
    _rewrite_manifest_version(tmp_path, profile, manifest, 1.0)

    evidence = source_files_for_body(tmp_path, profile, body_revision="body-r0001")

    assert evidence["manifest_sha256"] == file_sha256(manifest)
    assert evidence["source_files"][0]["sha256"] == file_sha256(media)
