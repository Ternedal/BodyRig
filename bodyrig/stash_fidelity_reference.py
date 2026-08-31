from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .stash_source import StashClient, StashSourceError

FORMAT = "bodyrig-fidelity-reference-set"
VERSION = 1
MAX_REFERENCES = 24
MAX_DISCOVERY_IMAGES = 100
MAX_IMAGE_BYTES = 32 * 1024 * 1024


class StashFidelityReferenceError(StashSourceError):
    pass


FetchBytes = Callable[[str], bytes]


def discover_performer_references(
    client: StashClient,
    performer_id: str,
    *,
    limit: int = 24,
) -> dict[str, Any]:
    performer_id = str(performer_id).strip()
    if not performer_id:
        raise StashFidelityReferenceError("performer id is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_REFERENCES:
        raise StashFidelityReferenceError(f"reference limit must be in 1..{MAX_REFERENCES}")
    discovery_limit = min(MAX_DISCOVERY_IMAGES, max(limit, limit * 4))

    query = """
query BodyRigFidelityReferences($id: ID!, $limit: Int!) {
  findPerformer(id: $id) {
    id
    name
    disambiguation
    image_path
  }
  findImages(
    image_filter: {performers: {value: [$id], modifier: INCLUDES}}
    filter: {page: 1, per_page: $limit, sort: "created_at", direction: DESC}
  ) {
    images {
      id
      title
      paths { image preview thumbnail }
      performers { id name }
    }
  }
}
"""
    try:
        data = client._graphql(query, {"id": performer_id, "limit": discovery_limit})
    except Exception as exc:
        raise StashFidelityReferenceError(f"Stash fidelity reference query failed: {exc}") from exc

    performer = data.get("findPerformer")
    if not isinstance(performer, Mapping) or str(performer.get("id") or "") != performer_id:
        raise StashFidelityReferenceError(f"Stash performer not found: {performer_id}")
    performer_name = str(performer.get("name") or "").strip()
    if not performer_name:
        raise StashFidelityReferenceError("Stash performer name is missing")

    candidates: list[dict[str, Any]] = []
    profile_url = str(performer.get("image_path") or "").strip()
    if profile_url:
        candidates.append(
            {
                "kind": "performer-profile",
                "stash_id": performer_id,
                "title": performer_name,
                "url": profile_url,
                "performer_count": 1,
                "exclusive_subject": True,
                "priority": 10_000,
            }
        )

    images = (data.get("findImages") or {}).get("images") or []
    for item in images:
        if not isinstance(item, Mapping) or not item.get("id"):
            continue
        performers = item.get("performers") or []
        performer_ids = [
            str(value.get("id"))
            for value in performers
            if isinstance(value, Mapping) and value.get("id") is not None
        ]
        if performer_id not in performer_ids:
            continue
        paths = item.get("paths") or {}
        if not isinstance(paths, Mapping):
            continue
        url = str(paths.get("image") or paths.get("preview") or paths.get("thumbnail") or "").strip()
        if not url:
            continue
        exclusive = len(set(performer_ids)) == 1
        candidates.append(
            {
                "kind": "stash-image",
                "stash_id": str(item["id"]),
                "title": str(item.get("title") or ""),
                "url": url,
                "performer_count": len(set(performer_ids)),
                "exclusive_subject": exclusive,
                "priority": 5_000 if exclusive else max(0, 1_000 - 100 * len(set(performer_ids))),
            }
        )

    by_url: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = item["url"]
        previous = by_url.get(key)
        if previous is None or item["priority"] > previous["priority"]:
            by_url[key] = item
    ranked = sorted(
        by_url.values(),
        key=lambda item: (-int(item["priority"]), int(item["performer_count"]), item["kind"], item["stash_id"]),
    )[:limit]
    if not ranked:
        raise StashFidelityReferenceError("Stash performer has no usable fidelity reference images")

    return {
        "performer": {
            "id": performer_id,
            "name": performer_name,
            "disambiguation": str(performer.get("disambiguation") or ""),
        },
        "references": [
            {
                key: item[key]
                for key in ("kind", "stash_id", "title", "url", "performer_count", "exclusive_subject")
            }
            for item in ranked
        ],
    }


def _default_fetcher(client: StashClient) -> FetchBytes:
    stash = urllib.parse.urlsplit(client.config.url)

    def fetch(url: str) -> bytes:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise StashFidelityReferenceError("Stash reference image URL must be absolute http(s)")
        if parsed.username or parsed.password or parsed.fragment:
            raise StashFidelityReferenceError("Stash reference image URL is not safe")
        if parsed.hostname.lower() != (stash.hostname or "").lower() or parsed.port != stash.port:
            raise StashFidelityReferenceError("Stash reference image URL must stay on the configured Stash origin")
        request = urllib.request.Request(url, method="GET")
        request.add_header("User-Agent", "BodyRig/0.1 FidelityReference")
        if client.config.api_key:
            request.add_header("ApiKey", client.config.api_key)
        try:
            with urllib.request.urlopen(request, timeout=client.config.timeout_seconds) as response:
                raw = response.read(MAX_IMAGE_BYTES + 1)
        except OSError as exc:
            raise StashFidelityReferenceError(f"could not fetch Stash reference image: {exc}") from exc
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise StashFidelityReferenceError("Stash reference image is empty or exceeds the byte limit")
        return raw

    return fetch


def _safe_suffix(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if raw.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return ".webp"
    raise StashFidelityReferenceError("reference image bytes are not PNG, JPEG or WebP")


def materialize_reference_set(
    client: StashClient,
    performer_id: str,
    *,
    output_dir: str | Path,
    limit: int = 24,
    fetch_bytes: FetchBytes | None = None,
) -> dict[str, Any]:
    catalog = discover_performer_references(client, performer_id, limit=limit)
    root = Path(output_dir).expanduser().resolve()
    if root.exists():
        raise StashFidelityReferenceError(f"fidelity reference output already exists: {root}")
    root.mkdir(parents=True, exist_ok=False)
    fetch = fetch_bytes or _default_fetcher(client)

    references: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    try:
        for index, item in enumerate(catalog["references"], start=1):
            raw = fetch(str(item["url"]))
            if not isinstance(raw, bytes) or not raw or len(raw) > MAX_IMAGE_BYTES:
                raise StashFidelityReferenceError("reference fetcher returned invalid image bytes")
            suffix = _safe_suffix(raw)
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            filename = f"reference-{index:02d}{suffix}"
            target = root / filename
            with target.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            references.append(
                {
                    "kind": item["kind"],
                    "stash_id": item["stash_id"],
                    "performer_count": item["performer_count"],
                    "exclusive_subject": item["exclusive_subject"],
                    "file": filename,
                    "sha256": digest,
                    "byte_count": len(raw),
                }
            )
        if not references:
            raise StashFidelityReferenceError("all discovered Stash reference images were duplicates or unusable")

        manifest_core = {
            "format": FORMAT,
            "version": VERSION,
            "performer": catalog["performer"],
            "stash_version": client.version(),
            "references": references,
            "privacy": {
                "contains_source_media": True,
                "private_workspace_only": True,
            },
            "semantics": "visual-fidelity-not-identity-verification",
        }
        canonical = json.dumps(
            manifest_core,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        manifest = dict(manifest_core)
        manifest["reference_set_sha256"] = hashlib.sha256(canonical).hexdigest()
        manifest_path = root / "reference-set.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return manifest
    except Exception:
        for child in root.iterdir() if root.exists() else []:
            child.unlink(missing_ok=True)
        root.rmdir()
        raise
