from __future__ import annotations

from pathlib import Path

from bodyrig.personality_stash_context import (
    inspect_personality_stash_context,
)
from bodyrig.stash_source import StashSourceError


def _profile(*, bound: bool = True) -> dict:
    return {
        "person_id": "person-" + "1" * 32,
        "display_name": "Performer 42",
        "source": (
            {
                "kind": "stash-performer",
                "performer_id": "42",
                "performer_name": "Target",
                "disambiguation": "fixture",
            }
            if bound
            else None
        ),
    }


class _Stash:
    def __init__(self, local_file: Path) -> None:
        self.local_file = local_file

    def version(self) -> str:
        return "v0.31.1"

    def performer(self, performer_id: str) -> dict[str, str]:
        return {
            "id": performer_id,
            "name": "Target live",
            "disambiguation": "live",
        }

    def scenes_for_performer(
        self,
        performer_id: str,
        *,
        limit: int = 200,
    ) -> list[dict]:
        assert performer_id == "42"
        assert limit == 200
        return [
            {
                "id": "scene-1",
                "title": "Solo source",
                "performers": [
                    {"id": "42", "name": "Target live"},
                ],
                "tags": [
                    {"name": "Interview"},
                    {"name": "Studio"},
                ],
                "files": [
                    {
                        "path": str(self.local_file),
                        "width": 3840,
                        "height": 2160,
                        "duration": 120.0,
                        "video_codec": "h264",
                    }
                ],
            },
            {
                "id": "scene-2",
                "title": "Multi source",
                "performers": [
                    {"id": "42", "name": "Target live"},
                    {"id": "7", "name": "Other"},
                ],
                "tags": [
                    {"name": "Interview"},
                    {"name": "Outdoor"},
                ],
                "files": [
                    {
                        "path": "/not/local.mp4",
                        "width": 1920,
                        "height": 1080,
                        "duration": 60.0,
                        "video_codec": "hevc",
                    }
                ],
            },
            {
                "id": "scene-wrong",
                "title": "Wrong performer",
                "performers": [
                    {"id": "99", "name": "Wrong"},
                ],
                "tags": [{"name": "MustNotCount"}],
                "files": [
                    {
                        "path": "/wrong.mp4",
                        "width": 7680,
                        "height": 4320,
                        "duration": 999.0,
                        "video_codec": "av1",
                    }
                ],
            },
        ]


class _BrokenStash(_Stash):
    def version(self) -> str:
        raise StashSourceError("stash unavailable")


def test_context_is_read_only_and_rechecks_performer_identity(
    tmp_path: Path,
) -> None:
    local_file = tmp_path / "scene.mp4"
    local_file.write_bytes(b"x")

    value = inspect_personality_stash_context(
        _profile(),
        stash_client=_Stash(local_file),
    )

    assert value["available"] is True
    assert value["stash_version"] == "v0.31.1"
    assert value["performer"] == {
        "id": "42",
        "name": "Target live",
        "disambiguation": "live",
    }
    assert value["scene_count_observed"] == 2
    assert value["solo_scene_count"] == 1
    assert value["multi_performer_scene_count"] == 1
    assert value["file_count_observed"] == 2
    assert value["local_file_count_observed"] == 1
    assert value["four_k_file_count_observed"] == 1
    assert value["total_file_duration_seconds_observed"] == 180.0
    assert value["video_codecs"] == [
        {"name": "h264", "count": 1},
        {"name": "hevc", "count": 1},
    ]
    assert value["top_tags"][0] == {
        "name": "Interview",
        "count": 2,
    }
    assert all(
        item["name"] != "MustNotCount"
        for item in value["top_tags"]
    )
    assert [item["scene_id"] for item in value["recent_scenes"]] == [
        "scene-1",
        "scene-2",
    ]
    assert value["authority"] == {
        "context_only": True,
        "personality_trait_authority": False,
        "personality_inference_authority": False,
        "biography_authority": False,
        "activation_authority": False,
        "production_authority": False,
    }
    assert "må ikke bruges som automatisk evidence" in value["guidance"]


def test_unbound_person_returns_non_authoritative_context() -> None:
    value = inspect_personality_stash_context(
        _profile(bound=False),
        stash_client=None,
    )

    assert value["available"] is False
    assert "ikke bundet" in value["reason"]
    assert value["performer"] is None
    assert value["authority"]["personality_trait_authority"] is False


def test_missing_stash_config_never_blocks_personality_authoring() -> None:
    value = inspect_personality_stash_context(
        _profile(),
        stash_client=None,
    )

    assert value["available"] is False
    assert "ikke konfigureret" in value["reason"]
    assert value["performer"]["id"] == "42"
    assert value["authority"]["activation_authority"] is False


def test_stash_failure_is_non_fatal_context_only(
    tmp_path: Path,
) -> None:
    local_file = tmp_path / "scene.mp4"
    local_file.write_bytes(b"x")

    value = inspect_personality_stash_context(
        _profile(),
        stash_client=_BrokenStash(local_file),
    )

    assert value["available"] is False
    assert value["reason"] == "stash unavailable"
    assert value["authority"]["context_only"] is True
    assert value["authority"]["production_authority"] is False
