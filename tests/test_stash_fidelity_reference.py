from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from bodyrig.stash_fidelity_reference import (
    StashFidelityReferenceError,
    discover_performer_references,
    materialize_reference_set,
)
from bodyrig.stash_source import StashClient, StashConfig


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32
JPG = b"\xff\xd8\xff" + b"y" * 32
WEBP = b"RIFF" + (24).to_bytes(4, "little") + b"WEBP" + b"z" * 24


def client() -> StashClient:
    def transport(query: str, variables: dict) -> dict:
        if "BodyRigFidelityReferences" in query:
            return {
                "findPerformer": {
                    "id": "42",
                    "name": "Test Performer",
                    "disambiguation": "",
                    "image_path": "http://stash.local/performer/42/image",
                },
                "findImages": {
                    "images": [
                        {
                            "id": "100",
                            "title": "solo",
                            "paths": {"image": "http://stash.local/image/100", "preview": "", "thumbnail": ""},
                            "performers": [{"id": "42", "name": "Test Performer"}],
                        },
                        {
                            "id": "101",
                            "title": "group",
                            "paths": {"image": "http://stash.local/image/101", "preview": "", "thumbnail": ""},
                            "performers": [
                                {"id": "42", "name": "Test Performer"},
                                {"id": "99", "name": "Other"},
                            ],
                        },
                        {
                            "id": "102",
                            "title": "wrong performer should be ignored",
                            "paths": {"image": "http://stash.local/image/102", "preview": "", "thumbnail": ""},
                            "performers": [{"id": "99", "name": "Other"}],
                        },
                    ]
                },
            }
        if "BodyRigStashVersion" in query:
            return {"version": {"version": "v0.31.1"}}
        raise AssertionError(query)

    return StashClient(StashConfig(url="http://stash.local", api_key="secret"), transport=transport)


def test_discovery_prefers_profile_and_solo_performer_images() -> None:
    result = discover_performer_references(client(), "42", limit=3)

    refs = result["references"]
    assert [item["kind"] for item in refs] == ["performer-profile", "stash-image", "stash-image"]
    assert refs[0]["exclusive_subject"] is True
    assert refs[1]["stash_id"] == "100"
    assert refs[1]["exclusive_subject"] is True
    assert refs[2]["stash_id"] == "101"
    assert refs[2]["exclusive_subject"] is False
    assert all(item["stash_id"] != "102" for item in refs)


def test_materialized_reference_set_is_hash_bound_and_path_local(tmp_path: Path) -> None:
    images = {
        "http://stash.local/performer/42/image": PNG,
        "http://stash.local/image/100": JPG,
        "http://stash.local/image/101": WEBP,
    }
    output = tmp_path / "references"

    result = materialize_reference_set(
        client(),
        "42",
        output_dir=output,
        limit=3,
        fetch_bytes=lambda url: images[url],
    )

    assert result["stash_version"] == "v0.31.1"
    assert result["privacy"] == {
        "contains_source_media": True,
        "private_workspace_only": True,
    }
    assert result["semantics"] == "visual-fidelity-not-identity-verification"
    assert len(result["references"]) == 3
    for item in result["references"]:
        raw = (output / item["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
    assert (output / "reference-set.json").is_file()
    assert len(result["reference_set_sha256"]) == 64


def test_duplicate_image_bytes_are_kept_once(tmp_path: Path) -> None:
    output = tmp_path / "refs"
    result = materialize_reference_set(
        client(),
        "42",
        output_dir=output,
        limit=3,
        fetch_bytes=lambda url: PNG,
    )

    assert len(result["references"]) == 1


def test_bad_image_bytes_fail_and_remove_partial_workspace(tmp_path: Path) -> None:
    output = tmp_path / "refs"

    with pytest.raises(StashFidelityReferenceError, match="not PNG, JPEG or WebP"):
        materialize_reference_set(
            client(),
            "42",
            output_dir=output,
            limit=1,
            fetch_bytes=lambda url: b"not-an-image",
        )

    assert not output.exists()


def test_discovery_requires_exact_performer_binding() -> None:
    def transport(query: str, variables: dict) -> dict:
        return {
            "findPerformer": {"id": "99", "name": "Wrong", "disambiguation": "", "image_path": ""},
            "findImages": {"images": []},
        }

    bad = StashClient(StashConfig(url="http://stash.local"), transport=transport)
    with pytest.raises(StashFidelityReferenceError, match="not found"):
        discover_performer_references(bad, "42")
