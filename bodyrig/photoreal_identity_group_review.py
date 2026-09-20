from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import math
import os
import shutil
import statistics
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageOps

from .photoreal_identity_bank import _canonical_bank_digest


REVIEW_FORMAT = "bodyrig-photoreal-identity-group-review-candidates"
REVIEW_VERSION = 1
PRIVATE_FORMAT = "bodyrig-photoreal-private-identity-group-review-index"
PRIVATE_VERSION = 1
ATTESTATION_FORMAT = "bodyrig-photoreal-identity-group-attestation"
ATTESTATION_VERSION = 1


class PhotorealIdentityGroupReviewError(RuntimeError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotorealIdentityGroupReviewError(f"required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityGroupReviewError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityGroupReviewError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotorealIdentityGroupReviewError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        dict(value),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _load_adapter(repo_root: Path):
    path = repo_root / "tools" / "photoreal_reference_vision_adapter_mesh.py"
    spec = importlib.util.spec_from_file_location(
        "bodyrig_identity_group_review_adapter",
        path,
    )
    if spec is None or spec.loader is None:
        raise PhotorealIdentityGroupReviewError(
            f"could not load reference adapter: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _validate_bank(bank: Mapping[str, Any], *, adapter_revision: str) -> tuple[str, str]:
    if bank.get("format") != "bodyrig-photoreal-identity-bank" or bank.get("version") != 1:
        raise PhotorealIdentityGroupReviewError("identity bank format/version mismatch")
    performer_id = str(bank.get("performer_id") or "").strip()
    if not performer_id:
        raise PhotorealIdentityGroupReviewError("identity bank performer id is missing")
    if str(bank.get("extractor_revision") or "").strip() != adapter_revision:
        raise PhotorealIdentityGroupReviewError(
            "identity bank extractor revision does not match current adapter bytes"
        )
    bank_sha = str(bank.get("identity_bank_sha256") or "").strip().lower()
    if len(bank_sha) != 64:
        raise PhotorealIdentityGroupReviewError("identity bank SHA-256 is invalid")
    if _canonical_bank_digest(bank) != bank_sha:
        raise PhotorealIdentityGroupReviewError("identity bank canonical digest mismatch")
    if bank.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityGroupReviewError("identity bank unexpectedly grants matching authority")
    if bank.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityGroupReviewError("identity bank unexpectedly grants training authority")
    if bank.get("production_activation") is not False:
        raise PhotorealIdentityGroupReviewError("identity bank unexpectedly grants production authority")
    return performer_id, bank_sha


def _validate_request(
    request: Mapping[str, Any],
    *,
    performer_id: str,
    bank: Mapping[str, Any],
    adapter_revision: str,
) -> dict[str, Mapping[str, Any]]:
    if (
        request.get("format") != "bodyrig-photoreal-identity-extractor-request"
        or request.get("version") != 1
    ):
        raise PhotorealIdentityGroupReviewError("Stage-7 identity request format/version mismatch")
    if str(request.get("performer_id") or "").strip() != performer_id:
        raise PhotorealIdentityGroupReviewError("Stage-7 identity request performer mismatch")
    if str(request.get("revision") or "").strip() != adapter_revision:
        raise PhotorealIdentityGroupReviewError("Stage-7 request adapter revision mismatch")
    if str(request.get("model_set_sha256") or "").strip().lower() != str(
        bank.get("model_set_sha256") or ""
    ).strip().lower():
        raise PhotorealIdentityGroupReviewError("Stage-7 request model-set mismatch")
    for field in (
        "identity_matching_authority",
        "teacher_training_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if request.get(field) is not False:
            raise PhotorealIdentityGroupReviewError(
                f"Stage-7 request crossed authority boundary: {field}"
            )
    sources = request.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PhotorealIdentityGroupReviewError("Stage-7 identity request has no sources")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in sources:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityGroupReviewError("Stage-7 identity request source is invalid")
        source_key = str(raw.get("source_key") or "").strip()
        if not source_key or source_key in result:
            raise PhotorealIdentityGroupReviewError(
                "Stage-7 identity request source key is missing/duplicate"
            )
        result[source_key] = raw
    return result


def _portrait_reference(
    portrait_root: Path,
    *,
    performer_id: str,
    expected_bank_sha: str,
) -> tuple[Path, str, float | None]:
    diagnostic_path = portrait_root / "portrait-seed-diagnostic.json"
    manifest_path = portrait_root / "references" / "reference-set.json"
    diagnostic = _read_json(diagnostic_path, label="portrait seed diagnostic")
    manifest = _read_json(manifest_path, label="portrait reference set")
    if diagnostic.get("format") != "bodyrig-photoreal-portrait-seed-diagnostic":
        raise PhotorealIdentityGroupReviewError("portrait seed diagnostic format mismatch")
    if str(diagnostic.get("performer_id") or "").strip() != performer_id:
        raise PhotorealIdentityGroupReviewError("portrait seed performer mismatch")
    if str(diagnostic.get("identity_bank_sha256") or "").strip().lower() != expected_bank_sha:
        raise PhotorealIdentityGroupReviewError("portrait seed targets a different identity bank")
    measurements = diagnostic.get("seed_measurements")
    refs = manifest.get("references")
    if not isinstance(measurements, list) or not isinstance(refs, list):
        raise PhotorealIdentityGroupReviewError("portrait seed evidence is incomplete")
    accepted_profile_files = {
        str(row.get("file") or "")
        for row in measurements
        if isinstance(row, Mapping)
        and row.get("accepted") is True
        and row.get("kind") == "performer-profile"
    }
    candidates = [
        row
        for row in refs
        if isinstance(row, Mapping)
        and row.get("kind") == "performer-profile"
        and str(row.get("file") or "") in accepted_profile_files
    ]
    if len(candidates) != 1:
        raise PhotorealIdentityGroupReviewError(
            "portrait seed review requires exactly one accepted performer-profile reference"
        )
    record = candidates[0]
    profile_path = (portrait_root / "references" / str(record["file"])).resolve()
    try:
        profile_path.relative_to((portrait_root / "references").resolve())
    except ValueError as exc:
        raise PhotorealIdentityGroupReviewError("portrait profile path escapes reference root") from exc
    expected_sha = str(record.get("sha256") or "").strip().lower()
    if _sha256_file(profile_path) != expected_sha:
        raise PhotorealIdentityGroupReviewError("portrait profile bytes changed")
    return profile_path, expected_sha, None


def _sample_key(timestamp: Any, eye: Any) -> tuple[float | None, str]:
    normalized = None if timestamp is None else round(float(timestamp), 6)
    return normalized, str(eye or "").strip()


def _match_review_frame(
    *,
    adapter: Any,
    runtime: Any,
    source: Mapping[str, Any],
    sample: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> Any:
    image, spatial = adapter.base._read_sample(runtime, source, sample)
    expected_sha = str(reference.get("frame_sha256") or "").strip().lower()
    matches: list[Any] = []
    if not spatial:
        if adapter.base._frame_sha(image) == expected_sha:
            matches.append(image)
    elif source.get("projection") == "equi":
        try:
            viewports = adapter.base.deproject_equirectangular_views(
                runtime,
                image,
                source.get("projection_authority"),
            )
        except adapter.base.PhotorealEquirectangularDeprojectionError as exc:
            raise PhotorealIdentityGroupReviewError(
                f"could not reproduce equirectangular reference frame: {exc}"
            ) from exc
        for _viewport_id, viewport_image in viewports:
            if adapter.base._frame_sha(viewport_image) == expected_sha:
                matches.append(viewport_image)
    else:
        raise PhotorealIdentityGroupReviewError(
            "review cannot reproduce non-equirectangular spatial identity reference"
        )
    if len(matches) != 1:
        raise PhotorealIdentityGroupReviewError(
            "identity reference frame SHA did not resolve to exactly one reproduced frame"
        )
    return matches[0]


def _fit_tile(image: Image.Image, *, size: tuple[int, int], label: str) -> Image.Image:
    tile = Image.new("RGB", size, "black")
    available = (size[0], size[1] - 38)
    fit = ImageOps.contain(image.convert("RGB"), available)
    tile.paste(
        fit,
        ((size[0] - fit.width) // 2, (available[1] - fit.height) // 2),
    )
    draw = ImageDraw.Draw(tile)
    draw.rectangle((0, size[1] - 38, size[0], size[1]), fill="black")
    draw.text((10, size[1] - 30), label[:100], fill="white")
    return tile


def _build_group_sheet(
    *,
    profile_path: Path,
    group_id: str,
    images: list[tuple[Any, Mapping[str, Any]]],
    seed_cosine: float | None,
    output: Path,
) -> str:
    try:
        with Image.open(profile_path) as opened:
            opened.load()
            profile = opened.convert("RGB")
    except Exception as exc:
        raise PhotorealIdentityGroupReviewError("portrait profile image is unreadable") from exc
    tiles = [
        _fit_tile(
            profile,
            size=(560, 560),
            label="PERFORMER PROFILE SEED",
        )
    ]
    for array, reference in images:
        try:
            rgb = array[:, :, ::-1]
            frame = Image.fromarray(rgb).convert("RGB")
        except Exception as exc:
            raise PhotorealIdentityGroupReviewError(
                "could not convert reproduced identity frame for review"
            ) from exc
        timestamp = reference.get("timestamp_seconds")
        eye = str(reference.get("eye") or "")
        label = f"{group_id} | {timestamp}s | {eye}"
        tiles.append(_fit_tile(frame, size=(560, 560), label=label))

    columns = 2
    rows = math.ceil(len(tiles) / columns)
    header = 70
    sheet = Image.new("RGB", (columns * 560, header + rows * 560), "black")
    draw = ImageDraw.Draw(sheet)
    score = "n/a" if seed_cosine is None else f"{seed_cosine:.6f}"
    draw.text(
        (14, 14),
        f"{group_id} | portrait-seed centroid cosine={score} | HUMAN IDENTITY REVIEW REQUIRED",
        fill="white",
    )
    for index, tile in enumerate(tiles):
        x = (index % columns) * 560
        y = header + (index // columns) * 560
        sheet.paste(tile, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG", optimize=False)
    return _sha256_file(output)


def _candidate_id(bank_sha: str, group_id: str) -> str:
    digest = hashlib.sha256(f"{bank_sha}\0{group_id}".encode("utf-8")).hexdigest()
    return "idgroup-" + digest[:32]


def _private_html(groups: list[Mapping[str, Any]], *, output: Path) -> None:
    cards = []
    for group in groups:
        sheet_name = html.escape(str(group["review_sheet_relative"]))
        group_id = html.escape(str(group["group_id"]))
        score = group.get("portrait_seed_centroid_cosine")
        score_text = "n/a" if score is None else f"{float(score):.6f}"
        candidate = html.escape(str(group["group_candidate_id"]))
        cards.append(
            "<section>"
            f"<h2>{group_id}</h2>"
            f"<p>Candidate: <code>{candidate}</code> · portrait cosine: {score_text}</p>"
            f"<img src=\"{sheet_name}\" alt=\"{group_id}\" loading=\"lazy\">"
            "</section>"
        )
    document = """<!doctype html>
<html><head><meta charset="utf-8"><title>BodyRig Photoreal identity group review</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:2rem}
section{margin:0 0 3rem;padding:1rem;border:1px solid #555;background:#191919}
img{max-width:100%;height:auto;display:block;background:#000}
code{word-break:break-all}
</style></head><body>
<h1>BodyRig Photoreal identity group review</h1>
<p>Compare every group with the performer profile seed. Machine cosine is diagnostic only; human identity review is authoritative.</p>
""" + "\n".join(cards) + "\n</body></html>\n"
    output.write_text(document, encoding="utf-8", newline="\n")


def prepare_review(
    *,
    identity_bank_path: Path,
    identity_request_path: Path,
    portrait_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    identity_bank_path = identity_bank_path.expanduser().resolve()
    identity_request_path = identity_request_path.expanduser().resolve()
    portrait_root = portrait_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise PhotorealIdentityGroupReviewError(f"review output already exists: {output_dir}")
    repo_root = Path(__file__).resolve().parents[1]
    adapter = _load_adapter(repo_root)
    adapter_revision = adapter._self_revision()
    bank = _read_json(identity_bank_path, label="identity bank")
    performer_id, bank_sha = _validate_bank(bank, adapter_revision=adapter_revision)
    request = _read_json(identity_request_path, label="Stage-7 identity request")
    sources = _validate_request(
        request,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
    )
    profile_path, profile_sha, _ = _portrait_reference(
        portrait_root,
        performer_id=performer_id,
        expected_bank_sha=bank_sha,
    )
    portrait_diagnostic = _read_json(
        portrait_root / "portrait-seed-diagnostic.json",
        label="portrait seed diagnostic",
    )
    portrait_scores = {
        str(row.get("group_id") or ""): row.get("profile_seed_centroid_cosine")
        for row in portrait_diagnostic.get("group_summaries") or []
        if isinstance(row, Mapping)
    }

    try:
        import cv2
        import numpy as np
    except Exception as exc:
        raise PhotorealIdentityGroupReviewError(
            "review preparation requires OpenCV and NumPy"
        ) from exc
    runtime = SimpleNamespace(cv2=cv2, np=np)

    references = bank.get("references")
    if not isinstance(references, list) or not references:
        raise PhotorealIdentityGroupReviewError("identity bank has no references")
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for raw in references:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityGroupReviewError("identity bank reference is invalid")
        group_id = str(raw.get("group_id") or "").strip()
        source_key = str(raw.get("source_key") or "").strip()
        source = sources.get(source_key)
        if source is None:
            raise PhotorealIdentityGroupReviewError(
                f"identity reference source not found in Stage-7 request: {source_key}"
            )
        if str(raw.get("source_sha256") or "").strip().lower() != str(
            source.get("source_sha256") or ""
        ).strip().lower():
            raise PhotorealIdentityGroupReviewError(
                f"identity reference source SHA mismatch: {source_key}"
            )
        samples = source.get("reference_samples")
        if not isinstance(samples, list):
            raise PhotorealIdentityGroupReviewError(
                f"Stage-7 source has no authorized samples: {source_key}"
            )
        target_key = _sample_key(raw.get("timestamp_seconds"), raw.get("eye"))
        matching_samples = [
            item
            for item in samples
            if isinstance(item, Mapping)
            and _sample_key(item.get("timestamp_seconds"), item.get("eye")) == target_key
        ]
        if len(matching_samples) != 1:
            raise PhotorealIdentityGroupReviewError(
                f"identity bank reference did not resolve to exactly one authorized Stage-7 sample: {source_key}"
            )
        grouped.setdefault(group_id, []).append(
            {
                "reference": raw,
                "request_sample": matching_samples[0],
            }
        )

    bodyrig_revision = str(os.environ.get("BODYRIG_REVISION") or "").strip().lower()
    if len(bodyrig_revision) != 40 or any(
        character not in "0123456789abcdef" for character in bodyrig_revision
    ):
        raise PhotorealIdentityGroupReviewError(
            "BODYRIG_REVISION must bind review preparation to one exact Git revision"
        )

    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent))
    try:
        sheets_root = stage / "private-review-sheets"
        sheets_root.mkdir(parents=True)
        public_groups: list[dict[str, Any]] = []
        private_groups: list[dict[str, Any]] = []
        for group_id in sorted(grouped):
            refs = grouped[group_id]
            reproduced: list[tuple[Any, Mapping[str, Any]]] = []
            public_samples: list[dict[str, Any]] = []
            source_keys: list[str] = []
            for bound in refs:
                ref = bound["reference"]
                request_sample = bound["request_sample"]
                source_key = str(ref["source_key"])
                source = sources[source_key]
                frame = _match_review_frame(
                    adapter=adapter,
                    runtime=runtime,
                    source=source,
                    sample=request_sample,
                    reference=ref,
                )
                reproduced.append((frame, ref))
                source_keys.append(source_key)
                public_samples.append(
                    {
                        "source_key_sha256": _sha256_bytes(source_key.encode("utf-8")),
                        "source_sha256": str(ref["source_sha256"]),
                        "timestamp_seconds": ref.get("timestamp_seconds"),
                        "request_timestamp_seconds": request_sample.get("timestamp_seconds"),
                        "eye": str(ref.get("eye")),
                        "frame_sha256": str(ref["frame_sha256"]),
                    }
                )
            candidate_id = _candidate_id(bank_sha, group_id)
            filename = f"{candidate_id}.png"
            sheet_path = sheets_root / filename
            score_raw = portrait_scores.get(group_id)
            score = None if score_raw is None else float(score_raw)
            sheet_sha = _build_group_sheet(
                profile_path=profile_path,
                group_id=group_id,
                images=reproduced,
                seed_cosine=score,
                output=sheet_path,
            )
            public_groups.append(
                {
                    "group_candidate_id": candidate_id,
                    "group_id": group_id,
                    "reference_count": len(refs),
                    "portrait_seed_centroid_cosine": None if score is None else round(score, 9),
                    "review_sheet_sha256": sheet_sha,
                    "samples": public_samples,
                }
            )
            private_groups.append(
                {
                    "group_candidate_id": candidate_id,
                    "group_id": group_id,
                    "source_keys": sorted(set(source_keys)),
                    "review_sheet": str(output_dir / "private-review-sheets" / filename),
                    "review_sheet_relative": f"private-review-sheets/{filename}",
                }
            )

        public_manifest = {
            "format": REVIEW_FORMAT,
            "version": REVIEW_VERSION,
            "bodyrig_revision": bodyrig_revision,
            "performer_id": performer_id,
            "identity_bank_sha256": bank_sha,
            "identity_bank_file_sha256": _sha256_file(identity_bank_path),
            "identity_request_sha256": _sha256_file(identity_request_path),
            "portrait_seed_diagnostic_sha256": _sha256_file(
                portrait_root / "portrait-seed-diagnostic.json"
            ),
            "portrait_profile_sha256": profile_sha,
            "group_count": len(public_groups),
            "groups": public_groups,
            "machine_portrait_cosine_authority": False,
            "human_identity_review_required": True,
            "identity_group_selection_authority": False,
            "identity_matching_authorized": False,
            "teacher_training_authorized": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        public_path = stage / "identity-group-review-candidates.json"
        _write_create_only(public_path, public_manifest)

        private_index = {
            "format": PRIVATE_FORMAT,
            "version": PRIVATE_VERSION,
            "bodyrig_revision": public_manifest["bodyrig_revision"],
            "performer_id": performer_id,
            "public_manifest_sha256": _sha256_file(public_path),
            "portrait_profile_path": str(profile_path),
            "groups": private_groups,
            "source_paths_private": True,
            "production_activation": False,
        }
        private_path = stage / "private-review-index.json"
        _write_create_only(private_path, private_index)
        html_groups = [
            {
                **row,
                "review_sheet_relative": f"private-review-sheets/{Path(str(row['review_sheet'])).name}",
                "portrait_seed_centroid_cosine": next(
                    item["portrait_seed_centroid_cosine"]
                    for item in public_groups
                    if item["group_id"] == row["group_id"]
                ),
            }
            for row in private_groups
        ]
        _private_html(html_groups, output=stage / "review-index.html")
        os.replace(stage, output_dir)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        **public_manifest,
        "public_manifest": str(output_dir / "identity-group-review-candidates.json"),
        "private_index": str(output_dir / "private-review-index.json"),
        "review_index": str(output_dir / "review-index.html"),
    }


def record_attestation(
    *,
    review_root: Path,
    attestation_revision: str,
    accept_groups: list[str],
    reject_groups: list[str],
    quality_note: str,
    confirm_identity: bool,
) -> dict[str, Any]:
    review_root = review_root.expanduser().resolve()
    public_path = review_root / "identity-group-review-candidates.json"
    private_path = review_root / "private-review-index.json"
    public = _read_json(public_path, label="identity group review manifest")
    private = _read_json(private_path, label="private identity group review index")
    if public.get("format") != REVIEW_FORMAT or public.get("version") != REVIEW_VERSION:
        raise PhotorealIdentityGroupReviewError("identity group review format/version mismatch")
    if private.get("format") != PRIVATE_FORMAT or private.get("version") != PRIVATE_VERSION:
        raise PhotorealIdentityGroupReviewError("private identity group review format/version mismatch")
    review_revision = str(public.get("bodyrig_revision") or "").strip().lower()
    if (
        len(review_revision) != 40
        or any(character not in "0123456789abcdef" for character in review_revision)
    ):
        raise PhotorealIdentityGroupReviewError("identity group review revision is invalid")
    if str(private.get("bodyrig_revision") or "").strip().lower() != review_revision:
        raise PhotorealIdentityGroupReviewError("public/private review revision mismatch")

    receipt_revision = str(attestation_revision or "").strip().lower()
    if (
        len(receipt_revision) != 40
        or any(character not in "0123456789abcdef" for character in receipt_revision)
    ):
        raise PhotorealIdentityGroupReviewError("attestation BodyRig revision is invalid")
    if private.get("public_manifest_sha256") != _sha256_file(public_path):
        raise PhotorealIdentityGroupReviewError("private review index lost public manifest binding")
    if public.get("human_identity_review_required") is not True:
        raise PhotorealIdentityGroupReviewError("identity group review did not require human review")
    for field in (
        "machine_portrait_cosine_authority",
        "identity_group_selection_authority",
        "identity_matching_authorized",
        "teacher_training_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if public.get(field) is not False:
            raise PhotorealIdentityGroupReviewError(
                f"identity group review crossed authority boundary: {field}"
            )
    if not confirm_identity:
        raise PhotorealIdentityGroupReviewError(
            "human identity attestation requires explicit confirmation"
        )
    note = str(quality_note or "").strip()
    if len(note) < 10:
        raise PhotorealIdentityGroupReviewError(
            "identity review QualityNote must contain at least 10 non-whitespace characters"
        )

    rows = public.get("groups")
    private_rows = private.get("groups")
    if not isinstance(rows, list) or not isinstance(private_rows, list):
        raise PhotorealIdentityGroupReviewError("identity group review lists are invalid")
    group_count = public.get("group_count")
    if (
        isinstance(group_count, bool)
        or not isinstance(group_count, int)
        or group_count != len(rows)
        or group_count != len(private_rows)
    ):
        raise PhotorealIdentityGroupReviewError("identity group review count binding is invalid")
    if str(private.get("performer_id") or "").strip() != str(public.get("performer_id") or "").strip():
        raise PhotorealIdentityGroupReviewError("public/private identity review performer mismatch")
    known = {
        str(item.get("group_id") or "").strip()
        for item in rows
        if isinstance(item, Mapping)
    }
    if not known or "" in known or len(known) != len(rows):
        raise PhotorealIdentityGroupReviewError("identity review group ids are invalid/duplicate")
    private_known = {
        str(item.get("group_id") or "").strip()
        for item in private_rows
        if isinstance(item, Mapping)
    }
    if private_known != known:
        raise PhotorealIdentityGroupReviewError("public/private identity review group sets differ")

    bank_sha = str(public.get("identity_bank_sha256") or "").strip().lower()
    if len(bank_sha) != 64 or any(character not in "0123456789abcdef" for character in bank_sha):
        raise PhotorealIdentityGroupReviewError("identity group review bank SHA-256 is invalid")
    public_by_group = {
        str(item["group_id"]): item
        for item in rows
        if isinstance(item, Mapping)
    }
    private_by_group = {
        str(item["group_id"]): item
        for item in private_rows
        if isinstance(item, Mapping)
    }
    for group_id in sorted(known):
        expected_candidate = _candidate_id(bank_sha, group_id)
        if str(public_by_group[group_id].get("group_candidate_id") or "") != expected_candidate:
            raise PhotorealIdentityGroupReviewError(
                f"public identity review candidate id is not bank/group bound: {group_id}"
            )
        if str(private_by_group[group_id].get("group_candidate_id") or "") != expected_candidate:
            raise PhotorealIdentityGroupReviewError(
                f"private identity review candidate id is not bank/group bound: {group_id}"
            )

    accepted = [str(value or "").strip() for value in accept_groups]
    rejected = [str(value or "").strip() for value in reject_groups]
    if any(not value for value in accepted + rejected):
        raise PhotorealIdentityGroupReviewError("accepted/rejected group ids cannot be blank")
    if len(set(accepted)) != len(accepted) or len(set(rejected)) != len(rejected):
        raise PhotorealIdentityGroupReviewError("accepted/rejected group ids contain duplicates")
    if set(accepted) & set(rejected):
        raise PhotorealIdentityGroupReviewError("a group cannot be both accepted and rejected")
    classified = set(accepted) | set(rejected)
    if classified != known:
        missing = sorted(known - classified)
        extra = sorted(classified - known)
        raise PhotorealIdentityGroupReviewError(
            f"human review must classify every group exactly once; missing={missing}; extra={extra}"
        )

    review_sheet_hashes: dict[str, str] = {}
    review_sheet_root = (review_root / "private-review-sheets").resolve()
    for group_id in sorted(known):
        path = Path(str(private_by_group[group_id].get("review_sheet") or "")).expanduser().resolve()
        try:
            path.relative_to(review_sheet_root)
        except ValueError as exc:
            raise PhotorealIdentityGroupReviewError(
                f"review sheet path escapes private review root for group {group_id}"
            ) from exc
        observed = _sha256_file(path)
        expected = str(public_by_group[group_id].get("review_sheet_sha256") or "").strip().lower()
        if observed != expected:
            raise PhotorealIdentityGroupReviewError(
                f"review sheet bytes changed for group {group_id}"
            )
        review_sheet_hashes[group_id] = observed

    result = {
        "format": ATTESTATION_FORMAT,
        "version": ATTESTATION_VERSION,
        "bodyrig_revision": receipt_revision,
        "review_bodyrig_revision": review_revision,
        "attestation_bodyrig_revision": receipt_revision,
        "performer_id": str(public.get("performer_id") or ""),
        "identity_bank_sha256": str(public.get("identity_bank_sha256") or ""),
        "review_manifest_sha256": _sha256_file(public_path),
        "private_review_index_sha256": _sha256_file(private_path),
        "portrait_profile_sha256": str(public.get("portrait_profile_sha256") or ""),
        "review_sheet_sha256_by_group": review_sheet_hashes,
        "accepted_group_ids": sorted(accepted),
        "rejected_group_ids": sorted(rejected),
        "accepted_group_count": len(accepted),
        "rejected_group_count": len(rejected),
        "human_identity_attested": True,
        "quality_note": note,
        "identity_group_selection_authority": True,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    output = review_root / "identity-group-attestation.json"
    _write_create_only(output, result)
    return {**result, "output": str(output)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare or attest Photoreal identity-group human review.")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--identity-bank", type=Path, required=True)
    prepare.add_argument("--identity-request", type=Path, required=True)
    prepare.add_argument("--portrait-root", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)

    attest = sub.add_parser("attest")
    attest.add_argument("--review-root", type=Path, required=True)
    attest.add_argument(
        "--attestation-revision",
        "--current-revision",
        dest="attestation_revision",
        required=True,
    )
    attest.add_argument("--accept-group", action="append", default=[])
    attest.add_argument("--reject-group", action="append", default=[])
    attest.add_argument("--quality-note", required=True)
    attest.add_argument("--confirm-identity", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = prepare_review(
            identity_bank_path=args.identity_bank,
            identity_request_path=args.identity_request,
            portrait_root=args.portrait_root,
            output_dir=args.output_dir,
        )
    else:
        result = record_attestation(
            review_root=args.review_root,
            attestation_revision=args.attestation_revision,
            accept_groups=list(args.accept_group),
            reject_groups=list(args.reject_group),
            quality_note=args.quality_note,
            confirm_identity=bool(args.confirm_identity),
        )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
