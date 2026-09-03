from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .person_profiles import PersonProfileError, add_personality_revision, load_profile
from .person_source_alignment import PersonSourceAlignmentError, file_sha256, write_binding
from .person_voice_source import PersonVoiceSourceError, source_files_for_body
from .personality_exemplars import PersonalityExemplarError, build_exemplar_candidates


class SourcePersonalityError(ValueError):
    pass


_TRANSCRIPT_SUFFIXES = {".srt", ".vtt", ".txt"}
_MAX_TRANSCRIPTS = 20
_MAX_EXEMPLARS = 12


@dataclass
class _InFlightBuild:
    done: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: BaseException | None = None


_INFLIGHT_GUARD = threading.Lock()
_INFLIGHT: dict[tuple[str, str, str, str], _InFlightBuild] = {}


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _persist_create_only(path: Path, value: Mapping[str, Any]) -> Path:
    raw = _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_bytes() != raw:
                raise SourcePersonalityError("source personality evidence path already contains different bytes")
        except OSError as exc:
            raise SourcePersonalityError("source personality evidence is unreadable") from exc
        return path
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise SourcePersonalityError("source personality evidence raced with different bytes")
        except OSError as exc:
            raise SourcePersonalityError("could not commit source personality evidence create-only") from exc
    finally:
        temp.unlink(missing_ok=True)
    return path


def _directory_transcript_files(
    directory: Path,
    cache: dict[str, tuple[tuple[str, Path], ...]],
) -> tuple[tuple[str, Path], ...]:
    """Scan one media directory at most once per source-personality build.

    Stash source sets commonly contain several clips from the same directory. A
    repeated Path.iterdir()+Path.is_file() pass can become very expensive on a
    large/network-backed media share. os.scandir keeps directory-entry metadata
    with the enumeration and the per-build cache preserves the exact discovery
    semantics without rescanning the same directory for every source clip.
    """
    key = os.path.normcase(str(directory))
    cached = cache.get(key)
    if cached is not None:
        return cached

    found: list[tuple[str, Path]] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if not entry.is_file():
                        continue
                except OSError:
                    continue
                name = entry.name
                if Path(name).suffix.casefold() not in _TRANSCRIPT_SUFFIXES:
                    continue
                found.append((name.casefold(), Path(entry.path).resolve()))
    except OSError:
        result: tuple[tuple[str, Path], ...] = ()
    else:
        found.sort(key=lambda item: item[0])
        result = tuple(found)
    cache[key] = result
    return result


def _sidecar_transcripts(
    media: Path,
    *,
    directory_cache: dict[str, tuple[tuple[str, Path], ...]] | None = None,
) -> list[Path]:
    """Return caption/transcript sidecars belonging to one exact media file.

    Stash captions live beside the scene and commonly use scene.en.srt / scene.vtt.
    We also accept scene.mp4.en.srt because existing libraries sometimes retain
    the full media filename. Prefix matching is intentionally narrow so a scene
    called ``foo`` cannot accidentally consume ``foobar.en.srt``.
    """
    cache = directory_cache if directory_cache is not None else {}
    entries = _directory_transcript_files(media.parent, cache)
    stem_prefix = media.stem.casefold() + "."
    full_prefix = media.name.casefold() + "."
    exact = {(media.stem + suffix).casefold() for suffix in _TRANSCRIPT_SUFFIXES}
    result = [
        path
        for name, path in entries
        if name in exact or name.startswith(stem_prefix) or name.startswith(full_prefix)
    ]
    result.sort(key=lambda path: path.name.casefold())
    return result


def _discover_transcripts(source_files: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    directory_cache: dict[str, tuple[tuple[str, Path], ...]] = {}
    for source in source_files:
        media = Path(str(source.get("path") or "")).expanduser().resolve()
        scene_id = str(source.get("scene_id") or "")
        for transcript in _sidecar_transcripts(media, directory_cache=directory_cache):
            key = os.path.normcase(str(transcript))
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "scene_id": scene_id,
                    "name": transcript.name,
                    "path": str(transcript),
                    "sha256": file_sha256(transcript),
                }
            )
            if len(found) >= _MAX_TRANSCRIPTS:
                return found
    return found


def _instructions(exemplars: list[str]) -> str:
    lines = [
        "Portray this person consistently rather than describing a persona from the outside.",
        "Do not invent biography, memories, relationships, private facts, beliefs, preferences or life events from appearance or video context.",
        "Keep factual claims grounded in the active ModelRig context.",
    ]
    if exemplars:
        lines.extend(
            [
                "The following utterances were observed in transcript/caption evidence tied to this exact Stash source. Use them only as speaking-style evidence: imitate phrasing, rhythm, register and conversational texture when useful, but never treat their factual content as current truth, biography or memory.",
                *[f"- {value}" for value in exemplars],
            ]
        )
    else:
        lines.extend(
            [
                "No transcript/caption evidence was available in the exact Stash source set, so keep verbal personality deliberately neutral rather than guessing psychological traits.",
                "Use a natural conversational register with moderate warmth, directness, detail and initiative until stronger source evidence is available.",
            ]
        )
    return "\n".join(lines)


def _build_source_personality(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    default_language: str = "en",
) -> dict[str, Any]:
    try:
        profile = load_profile(root, person_id)
        source = source_files_for_body(root, profile, body_revision=body_revision)
    except (PersonProfileError, PersonVoiceSourceError) as exc:
        raise SourcePersonalityError(str(exc)) from exc

    transcripts = _discover_transcripts(source["source_files"])
    exemplars: list[str] = []
    report: dict[str, Any] | None = None
    if transcripts:
        try:
            report = build_exemplar_candidates(
                [item["path"] for item in transcripts],
                suggested_limit=_MAX_EXEMPLARS,
            )
        except PersonalityExemplarError as exc:
            raise SourcePersonalityError(f"source transcript evidence is invalid: {exc}") from exc
        exemplars = list(report["suggested_exemplars"])

    evidence = {
        "format": "bodyrig-source-personality-evidence",
        "version": 1,
        "person_id": person_id,
        "performer": {
            "id": str(profile["source"]["performer_id"]),
            "name": str(profile["source"]["performer_name"]),
        },
        "body_revision": body_revision,
        "source_manifest_sha256": source["manifest_sha256"],
        "source_media": [
            {
                "scene_id": str(item["scene_id"]),
                "name": str(item["name"]),
                "sha256": str(item["sha256"]),
            }
            for item in source["source_files"]
        ],
        "transcripts": [
            {
                "scene_id": str(item["scene_id"]),
                "name": str(item["name"]),
                "sha256": str(item["sha256"]),
            }
            for item in transcripts
        ],
        "style_exemplars": exemplars,
        "transcript_candidate_count": int(report["candidate_count"]) if report else 0,
        "semantics": "observed-speaking-style-only-not-biography-memory-beliefs-or-inner-personality",
        "fallback": "neutral-verbal-style" if not exemplars else None,
    }
    evidence_sha = hashlib.sha256(_canonical_bytes(evidence)).hexdigest()
    evidence_path = Path(root).expanduser().resolve() / "personality-source-evidence" / person_id / f"{evidence_sha}.json"
    _persist_create_only(evidence_path, evidence)

    instructions = _instructions(exemplars)
    style_notes = (
        f"source-personality-v1 | body_revision={body_revision} | "
        f"source_manifest_sha256={source['manifest_sha256']} | "
        f"transcripts={len(transcripts)} | style_exemplars={len(exemplars)} | "
        f"evidence_sha256={evidence_sha}"
    )
    feedback = f"Automatic source-derived personality from {body_revision}"

    # Reload immediately before the create decision. Sequential retries still
    # revalidate source bytes, but must reuse an identical revision created by a
    # prior request rather than trusting the profile snapshot from before hashing.
    profile = load_profile(root, person_id)
    existing = next(
        (
            item
            for item in reversed(profile.get("personality_revisions", []))
            if item.get("instructions") == instructions
            and item.get("default_language") == default_language
            and item.get("style_notes") == style_notes
            and item.get("feedback") == feedback
        ),
        None,
    )
    try:
        if existing is None:
            profile = add_personality_revision(
                root,
                person_id,
                instructions=instructions,
                default_language=default_language,
                style_notes=style_notes,
                feedback=feedback,
            )
            revision_id = str(profile["personality_revisions"][-1]["revision_id"])
        else:
            revision_id = str(existing["revision_id"])
        profile = load_profile(root, person_id)
        binding = write_binding(
            root,
            profile,
            kind="personality",
            revision_id=revision_id,
            evidence_kind="stash-source-transcript-personality-v1" if transcripts else "stash-source-personality-fallback-v1",
            evidence_sha256=evidence_sha,
            evidence_ref=str(evidence_path),
            source_files=[
                {
                    "scene_id": str(item["scene_id"]),
                    "name": str(item["name"]),
                    "sha256": str(item["sha256"]),
                }
                for item in transcripts
            ],
        )
    except (PersonProfileError, PersonSourceAlignmentError) as exc:
        raise SourcePersonalityError(f"could not bind source personality candidate: {exc}") from exc

    return {
        "ok": True,
        "person_id": person_id,
        "body_revision": body_revision,
        "personality_revision": revision_id,
        "default_language": default_language,
        "transcript_count": len(transcripts),
        "style_exemplar_count": len(exemplars),
        "evidence_sha256": evidence_sha,
        "evidence_path": str(evidence_path),
        "source_binding": binding,
        "profile": profile,
    }


def build_source_personality(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    default_language: str = "en",
) -> dict[str, Any]:
    """Build once for identical concurrent requests, while keeping later retries strict.

    FastAPI executes this synchronous endpoint in a threadpool. Person Studio
    rerenders or a manual retry can therefore submit identical requests at the
    same time. Coalescing only an *in-flight* identical request prevents duplicate
    full-media SHA scans and duplicate revisions. Once the leader finishes, the
    entry is removed, so a later call performs the full fail-closed source-byte
    revalidation again.
    """
    root_key = os.path.normcase(str(Path(root).expanduser().resolve()))
    key = (root_key, str(person_id), str(body_revision), str(default_language))
    with _INFLIGHT_GUARD:
        flight = _INFLIGHT.get(key)
        if flight is None:
            flight = _InFlightBuild()
            _INFLIGHT[key] = flight
            leader = True
        else:
            leader = False

    if not leader:
        flight.done.wait()
        if flight.error is not None:
            if isinstance(flight.error, SourcePersonalityError):
                raise SourcePersonalityError(str(flight.error)) from flight.error
            raise RuntimeError("concurrent source personality build failed") from flight.error
        if flight.result is None:
            raise RuntimeError("concurrent source personality build completed without a result")
        return copy.deepcopy(flight.result)

    try:
        result = _build_source_personality(
            root,
            person_id,
            body_revision=body_revision,
            default_language=default_language,
        )
        flight.result = copy.deepcopy(result)
        return result
    except BaseException as exc:
        flight.error = exc
        raise
    finally:
        flight.done.set()
        with _INFLIGHT_GUARD:
            if _INFLIGHT.get(key) is flight:
                del _INFLIGHT[key]
