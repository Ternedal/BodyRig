from __future__ import annotations

import json
import math
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

MANIFEST_FORMAT = "bodyrig-stash-source-manifest"
MANIFEST_VERSION = 1
VIDEO_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".mov",
    ".m4v",
    ".webm",
    ".avi",
    ".wmv",
    ".ts",
    ".m2ts",
}


class StashSourceError(RuntimeError):
    pass


class StashGraphQLError(StashSourceError):
    pass


Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class StashConfig:
    url: str
    api_key: str = ""
    timeout_seconds: int = 20

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise StashSourceError("Stash URL must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise StashSourceError("Stash URL must not contain credentials")
        if parsed.query or parsed.fragment:
            raise StashSourceError("Stash URL must not contain query/fragment")
        if isinstance(self.timeout_seconds, bool) or not 1 <= self.timeout_seconds <= 120:
            raise StashSourceError("Stash timeout_seconds must be in 1..120")

    @property
    def graphql_url(self) -> str:
        return self.url.rstrip("/") + "/graphql"


@dataclass(frozen=True)
class SourceCandidate:
    scene_id: str
    scene_title: str
    path: str
    width: int
    height: int
    duration: float
    framerate: float
    performer_count: int
    score: float

    def to_json(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "scene_title": self.scene_title,
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "duration": round(self.duration, 3),
            "framerate": round(self.framerate, 3),
            "performer_count": self.performer_count,
            "score": round(self.score, 3),
        }


class StashClient:
    """Small local Stash GraphQL client for BodyRig source discovery.

    The API key is transport-only configuration. It is never included in source
    manifests or BodyRig provenance.
    """

    def __init__(self, config: StashConfig, *, transport: Transport | None = None) -> None:
        self.config = config
        self._transport = transport

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if self._transport is not None:
            result = self._transport(query, variables)
            if not isinstance(result, dict):
                raise StashGraphQLError("Stash transport returned a non-object")
            return result

        payload = json.dumps(
            {"query": query, "variables": variables},
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        request = urllib.request.Request(self.config.graphql_url, data=payload, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", "BodyRig/0.1 StashSource")
        if self.config.api_key:
            request.add_header("ApiKey", self.config.api_key)
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise StashGraphQLError(f"Stash HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise StashGraphQLError(f"Could not reach Stash: {exc}") from exc
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StashGraphQLError("Stash returned invalid JSON") from exc
        errors = body.get("errors")
        if errors:
            raise StashGraphQLError(f"Stash GraphQL error: {errors}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise StashGraphQLError("Stash GraphQL response has no data object")
        return data

    def version(self) -> str:
        data = self._graphql("query BodyRigStashVersion { version { version } }", {})
        version = (data.get("version") or {}).get("version")
        return str(version or "unknown")

    def search_performers(self, term: str, *, limit: int = 25) -> list[dict[str, str]]:
        term = term.strip()
        if not term:
            raise StashSourceError("performer search term is required")
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise StashSourceError("performer search limit must be in 1..100")
        query = """
query BodyRigFindPerformers($q: String!, $limit: Int!) {
  findPerformers(filter: {q: $q, per_page: $limit, sort: "name", direction: ASC}) {
    performers { id name disambiguation }
  }
}
"""
        data = self._graphql(query, {"q": term, "limit": limit})
        performers = (data.get("findPerformers") or {}).get("performers") or []
        result: list[dict[str, str]] = []
        for item in performers:
            if not isinstance(item, Mapping) or not item.get("id") or not item.get("name"):
                continue
            result.append(
                {
                    "id": str(item["id"]),
                    "name": str(item["name"]),
                    "disambiguation": str(item.get("disambiguation") or ""),
                }
            )
        return result

    def performer(self, performer_id: str) -> dict[str, str]:
        performer_id = str(performer_id).strip()
        if not performer_id:
            raise StashSourceError("performer id is required")
        query = """
query BodyRigPerformer($id: ID!) {
  findPerformer(id: $id) { id name disambiguation }
}
"""
        data = self._graphql(query, {"id": performer_id})
        item = data.get("findPerformer")
        if not isinstance(item, Mapping) or not item.get("id") or not item.get("name"):
            raise StashSourceError(f"Stash performer not found: {performer_id}")
        return {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "disambiguation": str(item.get("disambiguation") or ""),
        }

    @staticmethod
    def _scene_fields() -> str:
        return """
    id
    title
    files { path basename width height duration frame_rate video_codec size }
    tags { name }
    performers { id name }
"""

    def scenes_for_performer(self, performer_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        performer_id = str(performer_id).strip()
        if not performer_id:
            raise StashSourceError("performer id is required")
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise StashSourceError("scene limit must be in 1..1000")

        # Current Stash schema uses SceneFilterType.performers: MultiCriterionInput.
        # Keep a legacy performer_id fallback because older Stash releases used
        # that field and SkyPlayer installations may reasonably lag current Stash.
        current_query = f"""
query BodyRigPerformerScenes($id: ID!, $limit: Int!) {{
  findScenes(
    scene_filter: {{performers: {{value: [$id], modifier: INCLUDES}}}}
    filter: {{page: 1, per_page: $limit, sort: "created_at", direction: DESC}}
  ) {{
    count
    scenes {{ {self._scene_fields()} }}
  }}
}}
"""
        variables = {"id": performer_id, "limit": limit}
        try:
            data = self._graphql(current_query, variables)
        except StashGraphQLError as first_error:
            legacy_query = f"""
query BodyRigPerformerScenesLegacy($id: ID!, $limit: Int!) {{
  findScenes(
    scene_filter: {{performer_id: $id}}
    filter: {{page: 1, per_page: $limit, sort: "created_at", direction: DESC}}
  ) {{
    count
    scenes {{ {self._scene_fields()} }}
  }}
}}
"""
            try:
                data = self._graphql(legacy_query, variables)
            except StashGraphQLError as legacy_error:
                raise StashGraphQLError(
                    f"Stash performer scene query failed for current and legacy schemas: "
                    f"{first_error}; {legacy_error}"
                ) from legacy_error

        scenes = (data.get("findScenes") or {}).get("scenes") or []
        return [dict(item) for item in scenes if isinstance(item, Mapping)]


def _number(value: Any) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 0.0


def _score_candidate(
    *,
    width: int,
    height: int,
    duration: float,
    framerate: float,
    performer_count: int,
    tags: Iterable[str],
) -> float:
    pixels_m = (max(width, 0) * max(height, 0)) / 1_000_000.0
    score = min(pixels_m, 16.0) * 8.0
    if height >= 2160:
        score += 30.0
    elif height >= 1440:
        score += 22.0
    elif height >= 1080:
        score += 15.0
    elif height < 720:
        score -= 25.0

    if 20.0 <= duration <= 3600.0:
        score += 18.0
    elif duration < 8.0:
        score -= 35.0
    elif duration > 7200.0:
        score -= 8.0

    if framerate >= 50.0:
        score += 12.0
    elif framerate >= 24.0:
        score += 8.0
    elif 0 < framerate < 20.0:
        score -= 10.0

    if performer_count == 1:
        score += 70.0
    elif performer_count > 1:
        score -= 18.0 * (performer_count - 1)

    haystack = " ".join(tags).lower()
    if any(token in haystack for token in ("vr180", "vr360", "sbs", "side-by-side", "over-under")):
        # Projected/dual-eye material is still usable, but ordinary flat footage
        # is a cleaner first choice for identity/body recovery.
        score -= 20.0
    return score


def rank_sources(
    scenes: Iterable[Mapping[str, Any]],
    *,
    performer_id: str,
    max_sources: int = 10,
    require_local: bool = True,
) -> list[SourceCandidate]:
    if isinstance(max_sources, bool) or not 1 <= max_sources <= 10:
        raise StashSourceError("max_sources must be in 1..10")
    performer_id = str(performer_id).strip()
    if not performer_id:
        raise StashSourceError("performer id is required")

    by_path: dict[str, SourceCandidate] = {}
    for scene in scenes:
        scene_id = str(scene.get("id") or "").strip()
        if not scene_id:
            continue
        performers = scene.get("performers") or []
        performer_ids = {
            str(item.get("id"))
            for item in performers
            if isinstance(item, Mapping) and item.get("id") is not None
        }
        if performer_id not in performer_ids:
            # Never trust server-side filtering as the sole identity binding.
            continue
        performer_count = len(performer_ids)
        tags = [
            str(item.get("name") or "")
            for item in (scene.get("tags") or [])
            if isinstance(item, Mapping)
        ]
        title = str(scene.get("title") or f"Scene {scene_id}")
        for file_info in scene.get("files") or []:
            if not isinstance(file_info, Mapping):
                continue
            raw_path = str(file_info.get("path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            if path.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            if require_local and not path.is_file():
                continue
            try:
                normalized = str(path.resolve(strict=False))
            except OSError:
                continue
            width = int(_number(file_info.get("width")))
            height = int(_number(file_info.get("height")))
            duration = _number(file_info.get("duration"))
            framerate = _number(file_info.get("frame_rate"))
            score = _score_candidate(
                width=width,
                height=height,
                duration=duration,
                framerate=framerate,
                performer_count=performer_count,
                tags=tags,
            )
            candidate = SourceCandidate(
                scene_id=scene_id,
                scene_title=title,
                path=normalized,
                width=width,
                height=height,
                duration=duration,
                framerate=framerate,
                performer_count=performer_count,
                score=score,
            )
            existing = by_path.get(os.path.normcase(normalized))
            if existing is None or candidate.score > existing.score:
                by_path[os.path.normcase(normalized)] = candidate

    ranked = sorted(
        by_path.values(),
        key=lambda item: (-item.score, -item.height, -item.width, item.path.lower()),
    )
    return ranked[:max_sources]


def build_source_manifest(
    *,
    performer: Mapping[str, Any],
    candidates: list[SourceCandidate],
    stash_version: str,
    candidate_count: int,
) -> dict[str, Any]:
    if not candidates:
        raise StashSourceError("no usable local Stash source files found for performer")
    performer_id = str(performer.get("id") or "").strip()
    performer_name = str(performer.get("name") or "").strip()
    if not performer_id or not performer_name:
        raise StashSourceError("performer id/name are required for source manifest")
    return {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "source_kind": "stash-local",
        "performer": {
            "id": performer_id,
            "name": performer_name,
            "disambiguation": str(performer.get("disambiguation") or ""),
        },
        "stash_version": str(stash_version or "unknown"),
        "candidate_count": int(candidate_count),
        "selected": [item.to_json() for item in candidates],
    }


def write_source_manifest(path: str | Path, manifest: Mapping[str, Any]) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists():
        raise StashSourceError(f"source manifest already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return output
