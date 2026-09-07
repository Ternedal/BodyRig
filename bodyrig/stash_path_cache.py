from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit


FORMAT = "bodyrig-local-stash-path-map"
VERSION = 2
MAX_AGE = timedelta(days=7)
LEGACY_MAX_AGE = timedelta(hours=24)
_SOURCE_PREFIX = re.compile(r"^([A-Za-z]):\\(?:.*)?$")
_SHARE_ROOT = re.compile(r"^\\\\([^\\]+)\\VR_([A-Za-z])$", re.IGNORECASE)


class StashPathCacheError(RuntimeError):
    pass


def normalize_origin(url: str) -> str:
    try:
        parsed = urlsplit(str(url).strip())
    except ValueError as exc:
        raise StashPathCacheError("Stash URL is invalid") from exc
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise StashPathCacheError("Stash URL must be an absolute http(s) URL with a host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise StashPathCacheError("Stash URL contains an invalid port") from exc
    default_port = 80 if scheme == "http" else 443
    authority = host if port in {None, default_port} else f"{host}:{port}"
    return f"{scheme}://{authority}"


def _parse_utc(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise StashPathCacheError("cached path map has no updated_utc")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StashPathCacheError("cached path map updated_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise StashPathCacheError("cached path map updated_utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _normalized_performers(values: Sequence[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _validate_age(updated: datetime, *, now: datetime, max_age: timedelta) -> None:
    if now.tzinfo is None:
        raise StashPathCacheError("cache validation clock must be timezone-aware")
    now_utc = now.astimezone(timezone.utc)
    if updated > now_utc + timedelta(minutes=5):
        raise StashPathCacheError("cached path map timestamp is in the future")
    if now_utc - updated > max_age:
        raise StashPathCacheError("cached path map is stale")


def _validate_mapping(
    payload: Mapping[str, Any],
    *,
    host: str,
    is_dir: Callable[[str], bool],
) -> dict[str, str]:
    raw_mapping = payload.get("mapping")
    if not isinstance(raw_mapping, dict) or not raw_mapping:
        raise StashPathCacheError("cached path map mapping must be a non-empty object")

    mapping: dict[str, str] = {}
    for raw_source, raw_target in raw_mapping.items():
        if not isinstance(raw_source, str) or not isinstance(raw_target, str):
            raise StashPathCacheError("cached path map mapping keys/values must be strings")
        source = raw_source.strip().replace("/", "\\").rstrip("\\")
        target = raw_target.strip().replace("/", "\\").rstrip("\\")
        source_match = _SOURCE_PREFIX.fullmatch(source)
        share_match = _SHARE_ROOT.fullmatch(target)
        if source_match is None or share_match is None:
            raise StashPathCacheError("cached path map contains an unsupported source/share mapping")
        if share_match.group(1).casefold() != host.casefold():
            raise StashPathCacheError("cached path map share host differs from configured Stash host")
        if source_match.group(1).casefold() != share_match.group(2).casefold():
            raise StashPathCacheError("cached path map drive/share suffix mismatch")
        if not is_dir(target):
            raise StashPathCacheError(f"cached Stash SMB share is not currently readable: {target}")
        mapping[source] = target

    raw_proof = payload.get("proof")
    if not isinstance(raw_proof, list) or not raw_proof:
        raise StashPathCacheError("cached path map proof must be a non-empty array")
    proven: set[str] = set()
    for item in raw_proof:
        if not isinstance(item, dict):
            raise StashPathCacheError("cached path map proof entries must be objects")
        source = str(item.get("source_prefix") or "").strip().replace("/", "\\").rstrip("\\")
        share = str(item.get("share") or "").strip().replace("/", "\\").rstrip("\\")
        try:
            verified = int(item.get("verified_files"))
            candidates = int(item.get("candidate_files"))
        except (TypeError, ValueError) as exc:
            raise StashPathCacheError("cached path map proof counters are invalid") from exc
        if source not in mapping or mapping[source].casefold() != share.casefold():
            raise StashPathCacheError("cached path map proof does not match mapping")
        if verified < 1 or candidates < verified:
            raise StashPathCacheError("cached path map proof has no verified readable file")
        proven.add(source)
    if proven != set(mapping):
        raise StashPathCacheError("cached path map is missing proof for one or more mappings")
    return mapping


def validate_cache(
    payload: Mapping[str, Any],
    *,
    stash_url: str,
    performer_ids: Sequence[str],
    allow_performer_superset: bool = False,
    now: datetime | None = None,
    is_dir: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise StashPathCacheError("cached path map must be a JSON object")
    if payload.get("format") != FORMAT:
        raise StashPathCacheError("cached path map format is unsupported")

    origin = normalize_origin(stash_url)
    host = urlsplit(origin).hostname or ""
    current_performers = _normalized_performers(performer_ids)
    current_time = now or datetime.now(timezone.utc)
    directory_check = is_dir or (lambda value: Path(value).is_dir())
    version = payload.get("version")

    if version == VERSION:
        cached_origin = str(payload.get("stash_origin") or "").strip().lower().rstrip("/")
        if cached_origin != origin:
            raise StashPathCacheError("cached path map belongs to a different Stash origin")
        cached_performers = payload.get("performer_ids")
        if not isinstance(cached_performers, list) or not all(isinstance(item, str) for item in cached_performers):
            raise StashPathCacheError("cached path map performer_ids is invalid")
        normalized_cached = _normalized_performers(cached_performers)
        if allow_performer_superset:
            if not current_performers:
                raise StashPathCacheError("performer-superset cache validation requires an explicit performer scope")
            if not set(current_performers).issubset(normalized_cached):
                raise StashPathCacheError("cached path map does not cover the requested performer scope")
            mode = "v2-covering-scope" if normalized_cached != current_performers else "v2"
        else:
            if normalized_cached != current_performers:
                raise StashPathCacheError("cached path map performer scope changed")
            mode = "v2"
        updated = _parse_utc(payload.get("updated_utc"))
        _validate_age(updated, now=current_time, max_age=MAX_AGE)
    elif version == 1:
        cached_host = str(payload.get("stash_host") or "").strip()
        if cached_host.casefold() != host.casefold():
            raise StashPathCacheError("legacy cached path map belongs to a different Stash host")
        updated = _parse_utc(payload.get("updated_utc"))
        _validate_age(updated, now=current_time, max_age=LEGACY_MAX_AGE)
        mode = "legacy-v1"
    else:
        raise StashPathCacheError("cached path map version is unsupported")

    mapping = _validate_mapping(payload, host=host, is_dir=directory_check)
    return {
        "format": "bodyrig-stash-path-map-cache-validation",
        "version": 1,
        "ok": True,
        "cache_mode": mode,
        "stash_origin": origin,
        "performer_ids": current_performers,
        "mapping": mapping,
        "updated_utc": updated.isoformat().replace("+00:00", "Z"),
    }


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StashPathCacheError(f"cached path map is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise StashPathCacheError("cached path map must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate reusable local Stash path-map cache authority")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--stash-url", required=True)
    parser.add_argument("--performer-id", action="append", default=[])
    parser.add_argument(
        "--allow-performer-superset",
        action="store_true",
        help="Allow an explicit requested performer set to reuse a cache covering additional performers.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _read_payload(args.evidence.expanduser().resolve())
        result = validate_cache(
            payload,
            stash_url=args.stash_url,
            performer_ids=args.performer_id,
            allow_performer_superset=args.allow_performer_superset,
        )
    except StashPathCacheError as exc:
        print(f"BodyRig Stash path-map cache: MISS: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
