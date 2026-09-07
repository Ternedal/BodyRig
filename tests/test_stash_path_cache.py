from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bodyrig.stash_path_cache import StashPathCacheError, validate_cache


NOW = datetime(2026, 9, 7, 12, 30, tzinfo=timezone.utc)
SHARE = r"\\stashbox\VR_E"
SOURCE = r"E:\VR"


def _payload(*, version: int = 2, updated: datetime | None = None) -> dict:
    stamp = (updated or (NOW - timedelta(hours=1))).isoformat().replace("+00:00", "Z")
    value = {
        "format": "bodyrig-local-stash-path-map",
        "version": version,
        "stash_host": "stashbox",
        "mapping": {SOURCE: SHARE},
        "proof": [
            {
                "drive": "E",
                "source_prefix": SOURCE,
                "share": SHARE,
                "verified_files": 7,
                "candidate_files": 9,
            }
        ],
        "updated_utc": stamp,
    }
    if version == 2:
        value["stash_origin"] = "http://stashbox:9999"
        value["performer_ids"] = ["17", "42"]
    return value


def _live(path: str) -> bool:
    return path.casefold() == SHARE.casefold()


def test_v2_cache_requires_same_origin_scope_and_live_share() -> None:
    result = validate_cache(
        _payload(),
        stash_url="HTTP://STASHBOX:9999/some/base/path",
        performer_ids=["42", "17", "17"],
        now=NOW,
        is_dir=_live,
    )

    assert result["ok"] is True
    assert result["cache_mode"] == "v2"
    assert result["stash_origin"] == "http://stashbox:9999"
    assert result["performer_ids"] == ["17", "42"]
    assert result["mapping"] == {SOURCE: SHARE}


def test_one_performer_scope_can_reuse_cache_covering_more_performers() -> None:
    result = validate_cache(
        _payload(),
        stash_url="http://stashbox:9999",
        performer_ids=["17"],
        now=NOW,
        is_dir=_live,
    )

    assert result["ok"] is True
    assert result["cache_mode"] == "v2-covering-scope"
    assert result["performer_ids"] == ["17"]


def test_one_performer_scope_rejects_cache_that_does_not_cover_it() -> None:
    with pytest.raises(StashPathCacheError, match="does not cover the requested performer scope"):
        validate_cache(
            _payload(),
            stash_url="http://stashbox:9999",
            performer_ids=["99"],
            now=NOW,
            is_dir=_live,
        )


def test_v2_cache_rejects_different_stash_origin() -> None:
    with pytest.raises(StashPathCacheError, match="different Stash origin"):
        validate_cache(
            _payload(),
            stash_url="http://otherbox:9999",
            performer_ids=["17", "42"],
            now=NOW,
            is_dir=_live,
        )


def test_v2_cache_rejects_changed_multi_performer_scope() -> None:
    with pytest.raises(StashPathCacheError, match="performer scope changed"):
        validate_cache(
            _payload(),
            stash_url="http://stashbox:9999",
            performer_ids=["17", "99"],
            now=NOW,
            is_dir=_live,
        )


def test_v2_cache_rejects_stale_evidence() -> None:
    payload = _payload(updated=NOW - timedelta(days=8))
    with pytest.raises(StashPathCacheError, match="stale"):
        validate_cache(
            payload,
            stash_url="http://stashbox:9999",
            performer_ids=["17", "42"],
            now=NOW,
            is_dir=_live,
        )


def test_v2_cache_rejects_share_that_is_no_longer_live() -> None:
    with pytest.raises(StashPathCacheError, match="not currently readable"):
        validate_cache(
            _payload(),
            stash_url="http://stashbox:9999",
            performer_ids=["17", "42"],
            now=NOW,
            is_dir=lambda _path: False,
        )


def test_v2_cache_requires_proof_for_every_mapping() -> None:
    payload = _payload()
    payload["mapping"][r"F:\VR"] = r"\\stashbox\VR_F"
    with pytest.raises(StashPathCacheError, match="missing proof"):
        validate_cache(
            payload,
            stash_url="http://stashbox:9999",
            performer_ids=["17", "42"],
            now=NOW,
            is_dir=lambda _path: True,
        )


def test_v2_cache_rejects_drive_share_suffix_mismatch() -> None:
    payload = _payload()
    payload["mapping"] = {SOURCE: r"\\stashbox\VR_F"}
    payload["proof"][0]["share"] = r"\\stashbox\VR_F"
    with pytest.raises(StashPathCacheError, match="drive/share suffix mismatch"):
        validate_cache(
            payload,
            stash_url="http://stashbox:9999",
            performer_ids=["17", "42"],
            now=NOW,
            is_dir=lambda _path: True,
        )


def test_recent_v1_cache_is_accepted_only_as_legacy_warm_start() -> None:
    result = validate_cache(
        _payload(version=1, updated=NOW - timedelta(hours=3)),
        stash_url="http://stashbox:9999",
        performer_ids=["new-performer-does-not-bind-v1"],
        now=NOW,
        is_dir=_live,
    )
    assert result["cache_mode"] == "legacy-v1"


def test_v1_cache_expires_quickly_without_performer_scope_binding() -> None:
    with pytest.raises(StashPathCacheError, match="stale"):
        validate_cache(
            _payload(version=1, updated=NOW - timedelta(hours=25)),
            stash_url="http://stashbox:9999",
            performer_ids=["17"],
            now=NOW,
            is_dir=_live,
        )
