from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.package import MRBodyError, build_package, validate_manifest


def _manifest(name: str) -> dict[str, object]:
    return {
        "format": "modelrig-body",
        "format_version": 1,
        "id": "unicode-body",
        "name": name,
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": "0.1.0"},
    }


def test_manifest_name_rejects_json_escaped_lone_surrogate() -> None:
    name = json.loads(r'"\ud83d"')
    assert len(name) == 1

    with pytest.raises(MRBodyError, match="manifest.json: invalid name"):
        validate_manifest(_manifest(name))


def test_manifest_name_accepts_valid_supplementary_unicode() -> None:
    name = json.loads(r'"Body \ud83d\ude00"')
    assert name == "Body 😀"
    assert len(name) == 6

    validated = validate_manifest(_manifest(name))

    assert validated["name"] == name
    assert validated["name"].encode("utf-8").decode("utf-8") == name


def test_build_package_rejects_lone_surrogate_before_serialization(tmp_path: Path) -> None:
    with pytest.raises(MRBodyError, match="manifest.json: invalid name"):
        build_package(
            tmp_path / "invalid-name.mrbody",
            body_id="unicode-body",
            name="\ud83d",
            avatar_vrm=b"not-reached",
            bodyprint={},
            provenance={},
            thumbnail_png=b"not-reached",
        )
