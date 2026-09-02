from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bodyrig import ui_jobs
from bodyrig.person_profiles import add_body_revision, create_profile, load_profile
from bodyrig.person_source_alignment import file_sha256, read_binding, write_binding


class FakeVoiceRig:
    def __init__(self) -> None:
        self.remote_id = "f" * 32
        self.uploaded: list[Path] = []
        self.package = b"exact-mrvoice-package"

    def health(self) -> dict:
        return {"ok": True, "service": "voicerig", "version": "test"}

    def start_voice_job(self, *, name: str, language: str, files: list[Path], accent: str = "") -> dict:
        assert name == "Source Fixture"
        assert language == "da"
        assert accent == ""
        self.uploaded = list(files)
        return {
            "id": self.remote_id,
            "kind": "voice-build",
            "state": "queued",
            "progress": 0,
            "stage": "queued",
            "message": "queued",
            "error": None,
        }

    def voice_job(self, job_id: str) -> dict:
        assert job_id == self.remote_id
        return {
            "id": self.remote_id,
            "kind": "voice-build",
            "state": "succeeded",
            "progress": 100,
            "stage": "complete",
            "message": "done",
            "error": None,
            "result": {
                "voice": {"id": "source-voice", "name": "Source Fixture", "language": "da"},
                "package": "source-fixture.mrvoice",
            },
        }

    def package_bytes(self, package: str) -> bytes:
        assert package == "source-fixture.mrvoice"
        return self.package


def _source_profile(root: Path) -> tuple[dict, Path, Path]:
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


def _manager(tmp_path: Path, monkeypatch, fake: FakeVoiceRig) -> ui_jobs.UiJobManager:
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(ui_jobs, "person_library", lambda: tmp_path)
    monkeypatch.setattr(ui_jobs, "ui_jobs_dir", lambda: jobs)
    monkeypatch.setattr(ui_jobs, "_voicerig_client", lambda: fake)
    return ui_jobs.UiJobManager()


def test_source_voice_job_binds_exact_package_to_exact_stash_files(tmp_path: Path, monkeypatch) -> None:
    profile, manifest, media = _source_profile(tmp_path)
    fake = FakeVoiceRig()
    manager = _manager(tmp_path, monkeypatch, fake)

    started = manager.start_voice_build(profile["person_id"], body_revision="body-r0001", language="da")
    assert started["status"] == "queued"
    assert fake.uploaded == [media.resolve()]
    assert started["source_manifest_sha256"] == file_sha256(manifest)

    finished = manager.get(started["job_id"])
    assert finished["status"] == "succeeded"
    assert finished["voice_revision"] == "voice-r0001"
    assert finished["voice_package"] == "source-fixture.mrvoice"
    assert finished["package_sha256"] == hashlib.sha256(fake.package).hexdigest()

    updated = load_profile(tmp_path, profile["person_id"])
    assert updated["_source_alignment"]["components"]["voice"]["voice-r0001"]["aligned"] is True
    receipt = read_binding(tmp_path, updated, kind="voice", revision_id="voice-r0001")
    assert receipt["evidence"]["kind"] == "stash-voicerig-source-manifest-v1"
    assert receipt["evidence"]["sha256"] == file_sha256(manifest)
    assert receipt["evidence"]["source_files"] == [
        {"scene_id": "scene-7", "name": media.name, "sha256": file_sha256(media)}
    ]
    assert receipt["component"]["artifact_sha256"] == hashlib.sha256(fake.package).hexdigest()


def test_source_voice_job_fails_if_source_changes_after_upload(tmp_path: Path, monkeypatch) -> None:
    profile, _, media = _source_profile(tmp_path)
    fake = FakeVoiceRig()
    manager = _manager(tmp_path, monkeypatch, fake)

    started = manager.start_voice_build(profile["person_id"], body_revision="body-r0001", language="da")
    media.write_bytes(b"tampered-after-upload")

    finished = manager.get(started["job_id"])
    assert finished["status"] == "failed"
    assert finished["stage"] == "provenance_failed"
    assert "bytes no longer match" in finished["error"]
    updated = load_profile(tmp_path, profile["person_id"])
    assert updated["voice_revisions"] == []
