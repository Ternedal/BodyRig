from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD
from .photoidentity_nail_source_attestation import (
    PhotoIdentityNailAttestationError,
    _candidate_maps,
    _load_discovery,
    _sha256_file,
)

FORMAT = "bodyrig-photoidentity-private-nail-review-set"
VERSION = 1


class PhotoIdentityNailReviewPrepareError(RuntimeError):
    pass


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityNailReviewPrepareError(f"nail review index already exists: {path}")
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def prepare_review_set(sweep_root: Path) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    try:
        public_path, public, _, private = _load_discovery(sweep_root)
        public_map, private_map = _candidate_maps(public, private)
    except PhotoIdentityNailAttestationError as exc:
        raise PhotoIdentityNailReviewPrepareError(str(exc)) from exc

    review_root = sweep_root / "private-nail-source-review"
    if review_root.exists():
        raise PhotoIdentityNailReviewPrepareError("private nail source review set already exists")
    review_root.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    try:
        ordinal = 0
        for candidate_id in sorted(public_map):
            public_candidate = public_map[candidate_id]
            private_candidate = private_map[candidate_id]
            regions = public_candidate.get("regions")
            private_images = private_candidate.get("region_images")
            if not isinstance(regions, Mapping) or not isinstance(private_images, Mapping):
                raise PhotoIdentityNailReviewPrepareError("nail candidate region binding is invalid")
            for region in sorted(regions):
                entry = regions[region]
                source_image = private_images.get(region)
                if not isinstance(entry, Mapping) or not isinstance(source_image, str):
                    raise PhotoIdentityNailReviewPrepareError("nail candidate private image binding is invalid")
                quality = entry.get("source_quality")
                if isinstance(quality, bool) or not isinstance(quality, (int, float)):
                    raise PhotoIdentityNailReviewPrepareError("nail candidate source quality is invalid")
                quality_value = float(quality)
                if entry.get("review_eligible") is not True or quality_value < DETAIL_QUALITY_THRESHOLD:
                    continue
                source = Path(source_image).expanduser().resolve()
                expected_sha = str(entry.get("image_sha256") or "")
                if _sha256_file(source) != expected_sha:
                    raise PhotoIdentityNailReviewPrepareError("nail closeup bytes changed before source review")
                ordinal += 1
                reference = f"{candidate_id}:{region}"
                filename = f"{ordinal:03d}__{candidate_id}__{region}.png"
                target = review_root / filename
                shutil.copyfile(source, target)
                if _sha256_file(target) != expected_sha:
                    raise PhotoIdentityNailReviewPrepareError("copied nail source review bytes changed")
                rows.append(
                    {
                        "ordinal": ordinal,
                        "reference": reference,
                        "candidate_id": candidate_id,
                        "scene_id": str(public_candidate.get("scene_id") or ""),
                        "region": region,
                        "source_quality": round(quality_value, 4),
                        "native_crop_width": int(entry.get("native_crop_width", 0)),
                        "native_crop_height": int(entry.get("native_crop_height", 0)),
                        "image": filename,
                        "image_sha256": expected_sha,
                    }
                )
        index = {
            "format": FORMAT,
            "version": VERSION,
            "performer_id": str(public.get("performer_id") or ""),
            "bodyrig_revision": str(public.get("bodyrig_revision") or ""),
            "discovery_manifest_sha256": _sha256_file(public_path),
            "minimum_source_quality": DETAIL_QUALITY_THRESHOLD,
            "entries": rows,
            "source_only": True,
            "human_review_required": True,
            "nail_authority": False,
            "generic_guessing_permitted": False,
            "production_activation": False,
        }
        index_path = review_root / "review-index.json"
        refs_path = review_root / "review-refs.txt"
        _write_create_only(index_path, index)
        refs_path.write_text(
            "\n".join(
                f"{row['ordinal']:03d}\t{row['reference']}\tscene={row['scene_id']}\tquality={row['source_quality']:.4f}"
                for row in rows
            ) + ("\n" if rows else ""),
            encoding="utf-8",
            newline="\n",
        )
        return {
            **index,
            "review_root": str(review_root),
            "review_index": str(index_path),
            "review_refs": str(refs_path),
        }
    except Exception:
        shutil.rmtree(review_root, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a flat private source-only nail review set from eligible closeups.")
    parser.add_argument("--sweep-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_review_set(Path(args.sweep_root))
    except (OSError, PhotoIdentityNailReviewPrepareError) as exc:
        print(f"BodyRig nail source review preparation: FAIL: {exc}", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    for entry in result["entries"]:
        counts[entry["region"]] = counts.get(entry["region"], 0) + 1
    print(
        "BodyRig nail source review preparation: PASS | "
        f"eligible={len(result['entries'])} | "
        f"left-fingernails={counts.get('left_fingernails', 0)} | "
        f"right-fingernails={counts.get('right_fingernails', 0)} | "
        f"left-toenails={counts.get('left_toenails', 0)} | "
        f"right-toenails={counts.get('right_toenails', 0)}"
    )
    print(f"Review folder: {result['review_root']}")
    print(f"Reference list: {result['review_refs']}")
    print("Nail authority: FALSE until explicit human source attestation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
