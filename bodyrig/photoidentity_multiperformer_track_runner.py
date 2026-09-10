from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from .recover_cli import _run_wsl_file_protocol
from .wsl_adapter_bridge import make_wsl_path_converter

FORMAT = "bodyrig-phalp-track-review-batch"
VERSION = 1


class PhotoIdentityMultiTrackRunnerError(RuntimeError):
    pass


def _bridge_path() -> Path:
    return Path(__file__).resolve().parent / "bridges" / "hmr2_track_review_bridge.py"


def _hex_sha256(value: object, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise PhotoIdentityMultiTrackRunnerError(f"{label} is not canonical SHA-256")
    return text


def _validate_review(review: object, *, expected_source_index: int) -> dict[str, Any]:
    if not isinstance(review, Mapping):
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review must be an object")
    required = {
        "format",
        "version",
        "source_index",
        "tracks",
        "target_track_id",
        "human_identity_attestation_required",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "reconstruction_permitted",
        "production_activation",
    }
    if set(review) != required:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review fields changed")
    if review["format"] != "bodyrig-phalp-track-review" or review["version"] != 1:
        raise PhotoIdentityMultiTrackRunnerError("unsupported PHALP track review format/version")
    if review["source_index"] != expected_source_index:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review source index changed")
    if review["target_track_id"] is not None:
        raise PhotoIdentityMultiTrackRunnerError("machine track review illegally selected a target identity")
    for field in (
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "reconstruction_permitted",
        "production_activation",
    ):
        if review[field] is not False:
            raise PhotoIdentityMultiTrackRunnerError(f"PHALP track review illegally enabled {field}")
    if review["human_identity_attestation_required"] is not True:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review must require human identity attestation")
    tracks = review["tracks"]
    if not isinstance(tracks, list) or len(tracks) > 64:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review tracks are invalid")
    seen: set[str] = set()
    for track in tracks:
        if not isinstance(track, Mapping):
            raise PhotoIdentityMultiTrackRunnerError("PHALP track row must be an object")
        if set(track) != {
            "track_id",
            "observation_count",
            "first_timestamp_ms",
            "last_timestamp_ms",
            "samples",
        }:
            raise PhotoIdentityMultiTrackRunnerError("PHALP track row fields changed")
        track_id = str(track["track_id"] or "")
        if not track_id.startswith(f"s{expected_source_index:02d}-t") or len(track_id) > 160 or track_id in seen:
            raise PhotoIdentityMultiTrackRunnerError("PHALP track id is invalid or duplicated")
        seen.add(track_id)
        count = track["observation_count"]
        first = track["first_timestamp_ms"]
        last = track["last_timestamp_ms"]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 2
            or isinstance(first, bool)
            or not isinstance(first, int)
            or first < 0
            or isinstance(last, bool)
            or not isinstance(last, int)
            or last < first
        ):
            raise PhotoIdentityMultiTrackRunnerError("PHALP track bounds are invalid")
        samples = track["samples"]
        if not isinstance(samples, list) or not 1 <= len(samples) <= 12 or len(samples) > count:
            raise PhotoIdentityMultiTrackRunnerError("PHALP track samples are invalid")
        previous = -1
        for sample in samples:
            if not isinstance(sample, Mapping) or set(sample) != {"timestamp_ms", "confidence", "bbox_tlwh"}:
                raise PhotoIdentityMultiTrackRunnerError("PHALP track sample fields changed")
            timestamp = sample["timestamp_ms"]
            confidence = sample["confidence"]
            bbox = sample["bbox_tlwh"]
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= previous:
                raise PhotoIdentityMultiTrackRunnerError("PHALP track sample timestamps are invalid")
            previous = timestamp
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
                raise PhotoIdentityMultiTrackRunnerError("PHALP track sample confidence is invalid")
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise PhotoIdentityMultiTrackRunnerError("PHALP track sample bbox is invalid")
            try:
                _, _, width, height = (float(item) for item in bbox)
            except (TypeError, ValueError) as exc:
                raise PhotoIdentityMultiTrackRunnerError("PHALP track sample bbox is non-numeric") from exc
            if width <= 0.0 or height <= 0.0:
                raise PhotoIdentityMultiTrackRunnerError("PHALP track sample bbox has non-positive size")
    return dict(review)


def validate_track_review_batch(payload: object, *, expected_source_count: int) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review batch must be an object")
    required = {
        "format",
        "version",
        "adapter",
        "revision",
        "sources",
        "target_track_selected",
        "human_identity_attestation_required",
        "appearance_embeddings_exported",
        "source_paths_exported",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "reconstruction_permitted",
        "production_activation",
    }
    if set(payload) != required:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review batch fields changed")
    if payload["format"] != FORMAT or payload["version"] != VERSION:
        raise PhotoIdentityMultiTrackRunnerError("unsupported PHALP track review batch format/version")
    if payload["adapter"] != ADAPTER_NAME or payload["revision"] != ADAPTER_REVISION:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review adapter authority changed")
    if payload["target_track_selected"] is not False:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review batch illegally selected a target")
    if payload["human_identity_attestation_required"] is not True:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review batch must require human attestation")
    for field in (
        "appearance_embeddings_exported",
        "source_paths_exported",
        "biometric_identity_inference_used",
        "generic_guessing_permitted",
        "reconstruction_permitted",
        "production_activation",
    ):
        if payload[field] is not False:
            raise PhotoIdentityMultiTrackRunnerError(f"PHALP track review batch illegally enabled {field}")

    sources = payload["sources"]
    if not isinstance(sources, list) or len(sources) != expected_source_count:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review source count changed")
    normalized: list[dict[str, Any]] = []
    for expected_index, raw in enumerate(sources):
        if not isinstance(raw, Mapping) or set(raw) != {"source_index", "source_media_sha256", "review"}:
            raise PhotoIdentityMultiTrackRunnerError("PHALP source review row fields changed")
        if raw["source_index"] != expected_index:
            raise PhotoIdentityMultiTrackRunnerError("PHALP source review ordering changed")
        normalized.append(
            {
                "source_index": expected_index,
                "source_media_sha256": _hex_sha256(raw["source_media_sha256"], label="source media hash"),
                "review": _validate_review(raw["review"], expected_source_index=expected_index),
            }
        )
    return {**dict(payload), "sources": normalized}


def run_multiperformer_track_review(
    sources: Sequence[str | Path],
    *,
    external_python: str,
    four_d_humans_repo: str,
    phalp_repo: str,
    distribution: str,
    wsl_exe: str = "wsl.exe",
) -> dict[str, Any]:
    if not 1 <= len(sources) <= 10:
        raise PhotoIdentityMultiTrackRunnerError("track review accepts 1..10 local source clips")
    resolved = [Path(item).expanduser().resolve() for item in sources]
    missing = [str(path) for path in resolved if not path.is_file()]
    if missing:
        raise PhotoIdentityMultiTrackRunnerError("track review source is not a local file")
    for label, value in (
        ("external Python", external_python),
        ("4D-Humans repo", four_d_humans_repo),
        ("PHALP repo", phalp_repo),
    ):
        if not str(value).startswith("/"):
            raise PhotoIdentityMultiTrackRunnerError(f"WSL {label} must be an absolute Linux path")
    if not str(distribution).strip():
        raise PhotoIdentityMultiTrackRunnerError("WSL distribution is required")

    try:
        converter = make_wsl_path_converter(wsl_exe, distribution)
        bridge = converter(str(_bridge_path()))
        translated_sources = [converter(str(path)) for path in resolved]
    except Exception as exc:
        raise PhotoIdentityMultiTrackRunnerError(f"could not translate track review paths into WSL: {exc}") from exc

    request = {
        "format": "bodyrig-recovery-request",
        "version": 1,
        "sources": translated_sources,
    }
    target_command = [
        external_python,
        bridge,
        "--repo",
        four_d_humans_repo.rstrip("/"),
        "--phalp-repo",
        phalp_repo.rstrip("/"),
    ]
    try:
        returncode, stdout, stderr, staging = _run_wsl_file_protocol(
            wsl_exe=wsl_exe,
            distribution=distribution,
            external_python=external_python,
            target_command=target_command,
            request=request,
            converter=converter,
        )
    except Exception as exc:
        raise PhotoIdentityMultiTrackRunnerError(f"PHALP track review transport failed: {exc}") from exc
    if returncode != 0:
        detail = stderr.strip()[-2000:]
        suffix = f": {detail}" if detail else ""
        raise PhotoIdentityMultiTrackRunnerError(
            f"PHALP track review bridge exited {returncode}{suffix}; staging retained: {staging}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise PhotoIdentityMultiTrackRunnerError("PHALP track review bridge returned invalid JSON") from exc
    return validate_track_review_batch(payload, expected_source_count=len(resolved))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run pinned PHALP source-only track review for human identity attestation.")
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--python", required=True, dest="external_python")
    parser.add_argument("--repo", required=True, dest="four_d_humans_repo")
    parser.add_argument("--phalp-repo", required=True)
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_multiperformer_track_review(
            args.sources,
            external_python=args.external_python,
            four_d_humans_repo=args.four_d_humans_repo,
            phalp_repo=args.phalp_repo,
            distribution=args.distribution,
            wsl_exe=args.wsl_exe,
        )
        output = Path(args.out).expanduser().resolve()
        if output.exists():
            raise PhotoIdentityMultiTrackRunnerError(f"track review output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(output)
        print("Human identity attestation required: TRUE")
        print("Target track selected by machine: FALSE")
        return 0
    except (OSError, ValueError, PhotoIdentityMultiTrackRunnerError) as exc:
        print(f"BodyRig multi-performer track review: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
