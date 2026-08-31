from __future__ import annotations

import hashlib
import html
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

FORMAT = "bodyrig-personality-exemplar-candidates"
VERSION = 1
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_CANDIDATES = 200
MAX_EXEMPLARS = 12
TAG_RE = re.compile(r"<[^>]+>")
TIMESTAMP_RE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{3}\s*-->\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{3}.*$"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class PersonalityExemplarError(ValueError):
    pass


def _clean_text(value: str) -> str:
    value = html.unescape(TAG_RE.sub(" ", value))
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return value


def _blocks(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    return [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]


def parse_transcript_text(text: str) -> list[str]:
    if not isinstance(text, str):
        raise PersonalityExemplarError("transcript must be text")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    looks_timed = "-->" in normalized or normalized.lstrip().startswith("WEBVTT")
    candidates: list[str] = []

    if looks_timed:
        for block in _blocks(normalized):
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if not lines:
                continue
            if lines[0].upper() == "WEBVTT":
                lines = lines[1:]
            if lines and lines[0].isdigit():
                lines = lines[1:]
            lines = [line for line in lines if not TIMESTAMP_RE.match(line)]
            if not lines or lines[0].upper().startswith(("NOTE", "STYLE", "REGION")):
                continue
            cleaned = _clean_text(" ".join(lines))
            if cleaned:
                candidates.append(cleaned)
    else:
        raw_lines = [_clean_text(line) for line in normalized.split("\n")]
        raw_lines = [line for line in raw_lines if line]
        if len(raw_lines) <= 1 and raw_lines:
            raw_lines = [
                _clean_text(piece)
                for piece in SENTENCE_SPLIT_RE.split(raw_lines[0])
                if _clean_text(piece)
            ]
        candidates.extend(raw_lines)

    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not 3 <= len(candidate) <= 1000:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= MAX_CANDIDATES:
            break
    return result


def _source_digest(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PersonalityExemplarError(f"could not read transcript source: {path.name}") from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise PersonalityExemplarError(
            f"transcript source exceeds {MAX_SOURCE_BYTES} byte limit: {path.name}"
        )
    return hashlib.sha256(raw).hexdigest()


def _source_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PersonalityExemplarError(f"could not read transcript source: {path.name}") from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise PersonalityExemplarError(
            f"transcript source exceeds {MAX_SOURCE_BYTES} byte limit: {path.name}"
        )
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PersonalityExemplarError(
            f"transcript source must be UTF-8 text: {path.name}"
        ) from exc


def _evenly_spaced(values: list[str], limit: int) -> list[str]:
    if limit <= 0:
        return []
    if len(values) <= limit:
        return list(values)
    if limit == 1:
        return [values[len(values) // 2]]
    indexes = [round(index * (len(values) - 1) / (limit - 1)) for index in range(limit)]
    return [values[index] for index in indexes]


def build_exemplar_candidates(
    sources: Iterable[str | Path],
    *,
    suggested_limit: int = MAX_EXEMPLARS,
) -> dict[str, Any]:
    if isinstance(suggested_limit, bool) or not isinstance(suggested_limit, int) or not 1 <= suggested_limit <= MAX_EXEMPLARS:
        raise PersonalityExemplarError(f"suggested_limit must be in 1..{MAX_EXEMPLARS}")
    paths = [Path(item).expanduser().resolve() for item in sources]
    if not 1 <= len(paths) <= 20:
        raise PersonalityExemplarError("personality exemplar extraction requires 1..20 transcript sources")

    source_hashes: list[str] = []
    all_candidates: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise PersonalityExemplarError(f"transcript source not found: {path}")
        source_hashes.append(_source_digest(path))
        for item in parse_transcript_text(_source_text(path)):
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            all_candidates.append(item)
            if len(all_candidates) >= MAX_CANDIDATES:
                break
        if len(all_candidates) >= MAX_CANDIDATES:
            break

    if not all_candidates:
        raise PersonalityExemplarError("transcript sources contained no usable utterances")

    return {
        "format": FORMAT,
        "version": VERSION,
        "source_count": len(paths),
        "source_sha256": sorted(source_hashes),
        "candidate_count": len(all_candidates),
        "candidates": all_candidates,
        "suggested_exemplars": _evenly_spaced(all_candidates, suggested_limit),
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def write_create_only(path: str | Path, value: dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, target)
        except FileExistsError as exc:
            raise PersonalityExemplarError(f"exemplar output already exists: {target}") from exc
        except OSError as exc:
            raise PersonalityExemplarError("could not commit exemplar output create-only") from exc
    finally:
        temp.unlink(missing_ok=True)
    return target
