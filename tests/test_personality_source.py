from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bodyrig.person_profiles import add_body_revision, create_profile, load_profile
from bodyrig.person_source_alignment import file_sha256, read_binding, write_binding
from bodyrig.personality_source import SourcePersonalityError, _discover_transcripts, build_source_personality


def _source_profile(root: Path, *, with_transcript: bool) -> tuple[dict, Path, Path, Path | None]:
    media = root / "scene.mp4"
    media.write_bytes(b"exact-source-video")

    transcript: Path | None = None
    if with_transcript:
        transcript = root / "scene.en.srt"
        transcript.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nWell, that is actually pretty funny.\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nYeah, I mean, I would probably do that.\n",
            encoding="utf-8",
        )

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
    return load_profile(root, profile["person_id"]), manifest, media, transcript


def test_source_personality_uses_caption_utterances_as_style_only_evidence(tmp_path: Path) -> None:
    profile, _, _, transcript = _source_profile(tmp_path, with_transcript=True)
    assert transcript is not None

    result = build_source_personality(
        tmp_path,
        profile["person_id"],
        body_revision="body-r0001",
        default_language="en",
    )

    assert result["ok"] is True
    assert result["transcript_count"] == 1
    assert result["style_exemplar_count"] == 2
    assert result["personality_revision"] == "personality-r0001"
    evidence = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["semantics"] == "observed-speaking-style-only-not-biography-memory-beliefs-or-inner-personality"
    assert evidence["fallback"] is None
    assert evidence["transcripts"] == [
        {"scene_id": "scene-7", "name": transcript.name, "sha256": file_sha256(transcript)}
    ]
    assert "Well, that is actually pretty funny." in evidence["style_exemplars"]

    updated = load_profile(tmp_path, profile["person_id"])
    personality = updated["personality_revisions"][-1]
    assert "Well, that is actually pretty funny." in personality["instructions"]
    assert "never treat their factual content as current truth, biography or memory" in personality["instructions"]
    receipt = read_binding(
        tmp_path,
        updated,
        kind="personality",
        revision_id=result["personality_revision"],
    )
    assert receipt["evidence"]["kind"] == "stash-source-transcript-personality-v1"
    assert receipt["evidence"]["sha256"] == result["evidence_sha256"]


def test_source_personality_falls_back_neutrally_without_transcript(tmp_path: Path) -> None:
    profile, _, _, _ = _source_profile(tmp_path, with_transcript=False)

    result = build_source_personality(
        tmp_path,
        profile["person_id"],
        body_revision="body-r0001",
        default_language="en",
    )

    assert result["transcript_count"] == 0
    assert result["style_exemplar_count"] == 0
    updated = load_profile(tmp_path, profile["person_id"])
    personality = updated["personality_revisions"][-1]
    assert "keep verbal personality deliberately neutral" in personality["instructions"]
    assert "rather than guessing psychological traits" in personality["instructions"]
    receipt = read_binding(
        tmp_path,
        updated,
        kind="personality",
        revision_id=result["personality_revision"],
    )
    assert receipt["evidence"]["kind"] == "stash-source-personality-fallback-v1"


def test_source_personality_fails_closed_if_bound_media_bytes_changed(tmp_path: Path) -> None:
    profile, _, media, _ = _source_profile(tmp_path, with_transcript=True)
    media.write_bytes(b"tampered-after-body-binding")

    with pytest.raises(SourcePersonalityError, match="bytes no longer match"):
        build_source_personality(
            tmp_path,
            profile["person_id"],
            body_revision="body-r0001",
            default_language="en",
        )

    assert load_profile(tmp_path, profile["person_id"])["personality_revisions"] == []


def test_source_personality_is_idempotent_for_identical_evidence(tmp_path: Path) -> None:
    profile, _, _, _ = _source_profile(tmp_path, with_transcript=True)

    first = build_source_personality(
        tmp_path,
        profile["person_id"],
        body_revision="body-r0001",
        default_language="en",
    )
    second = build_source_personality(
        tmp_path,
        profile["person_id"],
        body_revision="body-r0001",
        default_language="en",
    )

    assert second["personality_revision"] == first["personality_revision"]
    assert second["evidence_sha256"] == first["evidence_sha256"]
    updated = load_profile(tmp_path, profile["person_id"])
    assert [item["revision_id"] for item in updated["personality_revisions"]] == ["personality-r0001"]


def test_concurrent_identical_source_personality_builds_share_one_inflight_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bodyrig.personality_source as module

    entered = threading.Event()
    release = threading.Event()
    calls: list[tuple[str, str, str]] = []

    def slow_build(root, person_id, *, body_revision, default_language="en"):
        calls.append((str(person_id), str(body_revision), str(default_language)))
        entered.set()
        assert release.wait(2)
        return {
            "ok": True,
            "person_id": person_id,
            "body_revision": body_revision,
            "personality_revision": "personality-r0001",
            "default_language": default_language,
        }

    monkeypatch.setattr(module, "_build_source_personality", slow_build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            module.build_source_personality,
            tmp_path,
            "person-" + "a" * 32,
            body_revision="body-r0001",
            default_language="en",
        )
        assert entered.wait(1)
        second = pool.submit(
            module.build_source_personality,
            tmp_path,
            "person-" + "a" * 32,
            body_revision="body-r0001",
            default_language="en",
        )
        time.sleep(0.05)
        assert len(calls) == 1
        release.set()
        assert first.result(timeout=2) == second.result(timeout=2)

    assert calls == [("person-" + "a" * 32, "body-r0001", "en")]


def test_completed_source_personality_build_is_not_cached_across_later_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bodyrig.personality_source as module

    calls = 0

    def fast_build(root, person_id, *, body_revision, default_language="en"):
        nonlocal calls
        calls += 1
        return {
            "ok": True,
            "person_id": person_id,
            "body_revision": body_revision,
            "personality_revision": "personality-r0001",
            "default_language": default_language,
        }

    monkeypatch.setattr(module, "_build_source_personality", fast_build)
    for _ in range(2):
        module.build_source_personality(
            tmp_path,
            "person-" + "b" * 32,
            body_revision="body-r0001",
            default_language="en",
        )
    assert calls == 2


def test_transcript_discovery_scans_shared_media_directory_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "scene-a.mp4"
    second = tmp_path / "scene-b.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    first_caption = tmp_path / "scene-a.en.srt"
    second_caption = tmp_path / "scene-b.vtt"
    first_caption.write_text("first caption", encoding="utf-8")
    second_caption.write_text("second caption", encoding="utf-8")

    import bodyrig.personality_source as module

    real_scandir = module.os.scandir
    calls: list[str] = []

    def counted_scandir(path):
        calls.append(str(Path(path).resolve()))
        return real_scandir(path)

    monkeypatch.setattr(module.os, "scandir", counted_scandir)
    result = _discover_transcripts(
        [
            {"scene_id": "a", "path": str(first)},
            {"scene_id": "b", "path": str(second)},
        ]
    )

    assert calls == [str(tmp_path.resolve())]
    assert [(item["scene_id"], item["name"]) for item in result] == [
        ("a", first_caption.name),
        ("b", second_caption.name),
    ]
