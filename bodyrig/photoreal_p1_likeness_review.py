from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

PAIRING_FORMAT = "bodyrig-photoreal-p1-heldout-pairing"
PAIRING_VERSION = 1
MANIFEST_FORMAT = "bodyrig-photoreal-p1-likeness-review-manifest"
MANIFEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p1-likeness-review"
RECEIPT_VERSION = 1


class PhotorealP1LikenessReviewError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP1LikenessReviewError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP1LikenessReviewError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP1LikenessReviewError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP1LikenessReviewError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP1LikenessReviewError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != 1.0:
        raise PhotorealP1LikenessReviewError(f"{label} format/version mismatch")


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealP1LikenessReviewError("P1 likeness artifact cannot be canonically serialized") from exc
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: str | Path) -> str:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise PhotorealP1LikenessReviewError(f"required file is missing or not regular: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str, *, label: str) -> Path:
    rel = Path(relative.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise PhotorealP1LikenessReviewError(f"{label} escapes root")
    result = (root / rel).resolve()
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise PhotorealP1LikenessReviewError(f"{label} escapes root") from exc
    return result


def _safe_criterion(value: Any) -> str:
    criterion = _text(value, label="P1 criterion", maximum=64)
    if any(not (character.isalnum() or character in "._-") for character in criterion):
        raise PhotorealP1LikenessReviewError(f"P1 criterion is not filename-safe: {criterion}")
    return criterion


def _validate_pairing(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value.get("format") != PAIRING_FORMAT:
        raise PhotorealP1LikenessReviewError("P1 pairing receipt format/version mismatch")
    _strict_v1(value.get("version"), label="P1 pairing receipt")
    if PAIRING_VERSION != 1:
        raise PhotorealP1LikenessReviewError("unsupported compiled P1 pairing version")
    claimed = _sha(value.get("p1_pairing_sha256"), label="P1 pairing SHA-256")
    if _digest(value, omit="p1_pairing_sha256") != claimed:
        raise PhotorealP1LikenessReviewError("P1 pairing receipt digest mismatch")
    for field, expected in (
        ("human_pairing_required", True),
        ("human_pairing_complete", True),
        ("held_out_pairing_authority", True),
        ("human_visual_likeness_acceptance", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotorealP1LikenessReviewError(f"P1 pairing authority mismatch: {field}")

    raw_pairs = value.get("pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise PhotorealP1LikenessReviewError("P1 pairing receipt contains no pairs")
    pairs: list[dict[str, Any]] = []
    criteria: set[str] = set()
    for raw in raw_pairs:
        if not isinstance(raw, Mapping):
            raise PhotorealP1LikenessReviewError("P1 pairing entry is invalid")
        criterion = _safe_criterion(raw.get("criterion"))
        if criterion in criteria:
            raise PhotorealP1LikenessReviewError("P1 pairing repeats criterion")
        criteria.add(criterion)
        pairs.append(
            {
                "criterion": criterion,
                "teacher_semantic_label": _text(
                    raw.get("teacher_semantic_label"),
                    label="teacher semantic label",
                    maximum=128,
                ),
                "teacher_render_index": raw.get("teacher_render_index"),
                "teacher_render_relative_path": _text(
                    raw.get("teacher_render_relative_path"),
                    label="teacher render path",
                ),
                "teacher_render_sha256": _sha(
                    raw.get("teacher_render_sha256"),
                    label="teacher render SHA-256",
                ),
                "held_out_frame_id": _text(
                    raw.get("held_out_frame_id"),
                    label="held-out frame id",
                    maximum=128,
                ),
                "held_out_group_id": _text(raw.get("held_out_group_id"), label="held-out group id"),
                "held_out_source_ref": _text(
                    raw.get("held_out_source_ref"),
                    label="held-out source ref",
                    maximum=20,
                ),
                "held_out_frame_sha256": _sha(
                    raw.get("held_out_frame_sha256"),
                    label="held-out frame SHA-256",
                ),
                "held_out_view_bin": _text(
                    raw.get("held_out_view_bin"),
                    label="held-out view bin",
                    maximum=64,
                ),
                "held_out_review_relative_path": _text(
                    raw.get("held_out_review_relative_path"),
                    label="held-out review path",
                ),
                "held_out_review_png_sha256": _sha(
                    raw.get("held_out_review_png_sha256"),
                    label="held-out review PNG SHA-256",
                ),
            }
        )
    return sorted(pairs, key=lambda item: item["criterion"])


def _copy_bound_image(
    source_root: Path,
    relative: str,
    expected_sha: str,
    target: Path,
    *,
    label: str,
) -> str:
    source = _safe_path(source_root, relative, label=label)
    if _sha256_file(source) != expected_sha:
        raise PhotorealP1LikenessReviewError(f"{label} bytes changed")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise PhotorealP1LikenessReviewError(f"P1 review pack target already exists: {target}")
    shutil.copy2(source, target)
    copied_sha = _sha256_file(target)
    if copied_sha != expected_sha:
        raise PhotorealP1LikenessReviewError(f"{label} copy SHA mismatch")
    return copied_sha


def _write_html(manifest: Mapping[str, Any], path: Path) -> None:
    rows: list[str] = []
    for pair in manifest.get("pairs") or []:
        if not isinstance(pair, Mapping):
            continue
        criterion = html.escape(str(pair.get("criterion") or ""))
        semantic = html.escape(str(pair.get("teacher_semantic_label") or ""))
        view_bin = html.escape(str(pair.get("held_out_view_bin") or ""))
        teacher_path = html.escape(str(pair.get("teacher_copy_relative_path") or ""))
        reference_path = html.escape(str(pair.get("reference_copy_relative_path") or ""))
        rows.append(
            "<section>"
            f"<h2>{criterion}</h2>"
            f"<p>Teacher orientation: <strong>{semantic}</strong> · held-out view bin: <strong>{view_bin}</strong></p>"
            "<div class=\"pair\">"
            f"<figure><figcaption>STATIC TEACHER</figcaption><a href=\"{teacher_path}\"><img src=\"{teacher_path}\" alt=\"teacher {criterion}\"></a></figure>"
            f"<figure><figcaption>HELD-OUT REAL REFERENCE</figcaption><a href=\"{reference_path}\"><img src=\"{reference_path}\" alt=\"reference {criterion}\"></a></figure>"
            "</div>"
            "<p class=\"decision\">Human decision required: PASS or FAIL for this criterion. Open either image at full resolution when needed.</p>"
            "</section>"
        )
    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>BodyRig P1 static teacher likeness review</title>
<style>
body{font-family:system-ui,sans-serif;background:#0f1115;color:#f3f5f7;margin:2rem;line-height:1.45}
.notice{border:1px solid #8b6f2d;background:#241e0f;padding:1rem;margin:1rem 0 2rem}
section{border-top:1px solid #363a43;padding:1.5rem 0 2.5rem}.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}
figure{margin:0;background:#181b21;padding:.75rem;border:1px solid #343944}figcaption{font-weight:700;margin-bottom:.5rem}
img{width:100%;height:auto;display:block;background:#000}.decision{font-weight:700}
@media(max-width:800px){.pair{grid-template-columns:1fr}}
</style></head><body>
<h1>BodyRig Photoreal V2 — P1 static teacher likeness review</h1>
<div class="notice"><strong>Human visual authority required.</strong> Compare the static teacher against the held-out real reference for every criterion. Training success and machine metrics do not count as a PASS. A failed criterion keeps P1 failed. This review can never activate production.</div>
""" + "\n".join(rows) + """
</body></html>
"""
    path.write_text(document, encoding="utf-8", newline="\n")


def build_likeness_review_pack(
    pairing: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    appearance_review_root: str | Path,
    output_root: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    pairs = _validate_pairing(pairing)
    teacher_root = Path(teacher_output_root).expanduser().resolve()
    reference_root = Path(appearance_review_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    if output.exists():
        if reuse_existing:
            return validate_likeness_review_pack(output, expected_pairing=pairing)
        raise PhotorealP1LikenessReviewError(f"P1 likeness review pack already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        materialized: list[dict[str, Any]] = []
        for pair in pairs:
            criterion = pair["criterion"]
            teacher_relative = f"teacher/{criterion}.png"
            reference_relative = f"reference/{criterion}.png"
            teacher_sha = _copy_bound_image(
                teacher_root,
                pair["teacher_render_relative_path"],
                pair["teacher_render_sha256"],
                stage / teacher_relative,
                label=f"teacher render for {criterion}",
            )
            reference_sha = _copy_bound_image(
                reference_root,
                pair["held_out_review_relative_path"],
                pair["held_out_review_png_sha256"],
                stage / reference_relative,
                label=f"held-out reference for {criterion}",
            )
            materialized.append(
                {
                    **pair,
                    "teacher_copy_relative_path": teacher_relative,
                    "teacher_copy_sha256": teacher_sha,
                    "reference_copy_relative_path": reference_relative,
                    "reference_copy_sha256": reference_sha,
                }
            )

        manifest: dict[str, Any] = {
            "format": MANIFEST_FORMAT,
            "version": MANIFEST_VERSION,
            "performer_id": _text(pairing.get("performer_id"), label="P1 performer", maximum=256),
            "selected_epoch_id": _text(pairing.get("selected_epoch_id"), label="P1 epoch", maximum=256),
            "teacher_input_sha256": _sha(pairing.get("teacher_input_sha256"), label="teacher input SHA-256"),
            "semantic_alignment_sha256": _sha(
                pairing.get("semantic_alignment_sha256"),
                label="semantic alignment SHA-256",
            ),
            "p1_pairing_sha256": _sha(pairing.get("p1_pairing_sha256"), label="P1 pairing SHA-256"),
            "criterion_count": len(materialized),
            "pairs": materialized,
            "human_visual_review_required": True,
            "human_visual_review_complete": False,
            "p1_static_teacher_acceptance_authority": False,
            "human_visual_likeness_acceptance": False,
            "p2_animation_authorized": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        html_path = stage / "review-index.html"
        _write_html(manifest, html_path)
        manifest["review_index_sha256"] = _sha256_file(html_path)
        manifest["p1_likeness_review_manifest_sha256"] = _digest(
            manifest,
            omit="p1_likeness_review_manifest_sha256",
        )
        (stage / "p1-likeness-review-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return validate_likeness_review_pack(output, expected_pairing=pairing)


def validate_likeness_review_pack(
    output_root: str | Path,
    *,
    expected_pairing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    output = Path(output_root).expanduser().resolve()
    manifest_path = output / "p1-likeness-review-manifest.json"
    html_path = output / "review-index.html"
    manifest = _read_json(manifest_path, label="P1 likeness review manifest")
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PhotorealP1LikenessReviewError("P1 likeness review manifest format/version mismatch")
    _strict_v1(manifest.get("version"), label="P1 likeness review manifest")
    claimed = _sha(
        manifest.get("p1_likeness_review_manifest_sha256"),
        label="P1 likeness review manifest SHA-256",
    )
    if _digest(manifest, omit="p1_likeness_review_manifest_sha256") != claimed:
        raise PhotorealP1LikenessReviewError("P1 likeness review manifest digest mismatch")
    if _sha(manifest.get("review_index_sha256"), label="P1 review HTML SHA-256") != _sha256_file(html_path):
        raise PhotorealP1LikenessReviewError("P1 likeness review HTML bytes changed")
    for field, expected in (
        ("human_visual_review_required", True),
        ("human_visual_review_complete", False),
        ("p1_static_teacher_acceptance_authority", False),
        ("human_visual_likeness_acceptance", False),
        ("p2_animation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected:
            raise PhotorealP1LikenessReviewError(f"P1 review manifest authority mismatch: {field}")

    pairs = manifest.get("pairs")
    count = manifest.get("criterion_count")
    if not isinstance(pairs, list) or not pairs:
        raise PhotorealP1LikenessReviewError("P1 review manifest contains no criterion pairs")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(pairs):
        raise PhotorealP1LikenessReviewError("P1 review criterion count mismatch")
    criteria: set[str] = set()
    for raw in pairs:
        if not isinstance(raw, Mapping):
            raise PhotorealP1LikenessReviewError("P1 review pair is invalid")
        criterion = _safe_criterion(raw.get("criterion"))
        if criterion in criteria:
            raise PhotorealP1LikenessReviewError("P1 review repeats criterion")
        criteria.add(criterion)
        for relative_field, sha_field, label in (
            ("teacher_copy_relative_path", "teacher_copy_sha256", "teacher copy"),
            ("reference_copy_relative_path", "reference_copy_sha256", "reference copy"),
        ):
            path = _safe_path(output, _text(raw.get(relative_field), label=relative_field), label=label)
            if _sha(raw.get(sha_field), label=f"{label} SHA-256") != _sha256_file(path):
                raise PhotorealP1LikenessReviewError(f"P1 review {label} bytes changed")

    if expected_pairing is not None:
        _validate_pairing(expected_pairing)
        if _sha(manifest.get("p1_pairing_sha256"), label="manifest P1 pairing SHA-256") != _sha(
            expected_pairing.get("p1_pairing_sha256"),
            label="expected P1 pairing SHA-256",
        ):
            raise PhotorealP1LikenessReviewError("P1 review pack targets different pairing receipt")
        expected_criteria = {
            _safe_criterion(item.get("criterion"))
            for item in expected_pairing.get("pairs") or []
            if isinstance(item, Mapping)
        }
        if criteria != expected_criteria:
            raise PhotorealP1LikenessReviewError("P1 review pack criterion universe differs from pairing receipt")
    return manifest


def record_likeness_review(
    manifest: Mapping[str, Any],
    *,
    decisions: Mapping[str, str],
    reviewed_by: str,
    review_notes: str,
    confirm_review_complete: bool,
) -> dict[str, Any]:
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PhotorealP1LikenessReviewError("P1 likeness review manifest format/version mismatch")
    _strict_v1(manifest.get("version"), label="P1 likeness review manifest")
    claimed = _sha(
        manifest.get("p1_likeness_review_manifest_sha256"),
        label="P1 likeness review manifest SHA-256",
    )
    if _digest(manifest, omit="p1_likeness_review_manifest_sha256") != claimed:
        raise PhotorealP1LikenessReviewError("P1 likeness review manifest digest mismatch")
    if confirm_review_complete is not True:
        raise PhotorealP1LikenessReviewError("explicit human P1 review completion confirmation is required")
    for field, expected in (
        ("human_visual_review_required", True),
        ("human_visual_review_complete", False),
        ("p1_static_teacher_acceptance_authority", False),
        ("human_visual_likeness_acceptance", False),
        ("p2_animation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected:
            raise PhotorealP1LikenessReviewError(f"P1 review manifest authority mismatch: {field}")

    raw_pairs = manifest.get("pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise PhotorealP1LikenessReviewError("P1 review manifest contains no pairs")
    criteria = [_safe_criterion(item.get("criterion")) for item in raw_pairs if isinstance(item, Mapping)]
    if len(criteria) != len(raw_pairs) or len(criteria) != len(set(criteria)):
        raise PhotorealP1LikenessReviewError("P1 review criterion universe is invalid")
    if set(decisions) != set(criteria):
        raise PhotorealP1LikenessReviewError("P1 review must decide PASS/FAIL for every criterion exactly once")
    normalized_decisions: list[dict[str, str]] = []
    for criterion in sorted(criteria):
        decision = _text(decisions.get(criterion), label=f"P1 decision {criterion}", maximum=16).lower()
        if decision not in {"pass", "fail"}:
            raise PhotorealP1LikenessReviewError(f"P1 decision must be pass/fail: {criterion}")
        normalized_decisions.append({"criterion": criterion, "decision": decision})

    reviewer = _text(reviewed_by, label="P1 likeness reviewer", maximum=256)
    if not isinstance(review_notes, str) or not review_notes.strip() or len(review_notes) > 8192:
        raise PhotorealP1LikenessReviewError("P1 likeness review notes are invalid")
    all_pass = all(item["decision"] == "pass" for item in normalized_decisions)
    receipt: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": _text(manifest.get("performer_id"), label="P1 performer", maximum=256),
        "selected_epoch_id": _text(manifest.get("selected_epoch_id"), label="P1 epoch", maximum=256),
        "teacher_input_sha256": _sha(manifest.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "semantic_alignment_sha256": _sha(
            manifest.get("semantic_alignment_sha256"),
            label="semantic alignment SHA-256",
        ),
        "p1_pairing_sha256": _sha(manifest.get("p1_pairing_sha256"), label="P1 pairing SHA-256"),
        "p1_likeness_review_manifest_sha256": claimed,
        "criterion_results": normalized_decisions,
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "human_visual_review_required": True,
        "human_visual_review_complete": True,
        "p1_static_teacher_status": "pass" if all_pass else "fail",
        "p1_static_teacher_acceptance_authority": all_pass,
        "human_visual_likeness_acceptance": all_pass,
        "p2_animation_authorized": all_pass,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p1_likeness_review_sha256"] = _digest(receipt, omit="p1_likeness_review_sha256")
    return receipt


def validate_likeness_review_receipt(
    receipt: Mapping[str, Any],
    *,
    review_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if receipt.get("format") != RECEIPT_FORMAT:
        raise PhotorealP1LikenessReviewError("P1 likeness review receipt format/version mismatch")
    _strict_v1(receipt.get("version"), label="P1 likeness review receipt")
    claimed = _sha(
        receipt.get("p1_likeness_review_sha256"),
        label="P1 likeness review receipt SHA-256",
    )
    if _digest(receipt, omit="p1_likeness_review_sha256") != claimed:
        raise PhotorealP1LikenessReviewError("P1 likeness review receipt digest mismatch")

    status = _text(receipt.get("p1_static_teacher_status"), label="P1 static teacher status", maximum=16).lower()
    if status not in {"pass", "fail"}:
        raise PhotorealP1LikenessReviewError("P1 static teacher status is invalid")
    expected = status == "pass"
    for field, wanted in (
        ("human_visual_review_required", True),
        ("human_visual_review_complete", True),
        ("p1_static_teacher_acceptance_authority", expected),
        ("human_visual_likeness_acceptance", expected),
        ("p2_animation_authorized", expected),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not wanted:
            raise PhotorealP1LikenessReviewError(f"P1 likeness receipt authority mismatch: {field}")

    raw_results = receipt.get("criterion_results")
    if not isinstance(raw_results, list) or not raw_results:
        raise PhotorealP1LikenessReviewError("P1 likeness review receipt has no criterion results")
    decisions: dict[str, str] = {}
    for raw in raw_results:
        if not isinstance(raw, Mapping):
            raise PhotorealP1LikenessReviewError("P1 likeness review criterion result is invalid")
        criterion = _safe_criterion(raw.get("criterion"))
        if criterion in decisions:
            raise PhotorealP1LikenessReviewError("P1 likeness review receipt repeats criterion")
        decision = _text(raw.get("decision"), label=f"P1 decision {criterion}", maximum=16).lower()
        if decision not in {"pass", "fail"}:
            raise PhotorealP1LikenessReviewError(f"P1 decision must be pass/fail: {criterion}")
        decisions[criterion] = decision
    if all(value == "pass" for value in decisions.values()) is not expected:
        raise PhotorealP1LikenessReviewError("P1 likeness status does not match criterion decisions")

    if review_manifest is not None:
        if review_manifest.get("format") != MANIFEST_FORMAT:
            raise PhotorealP1LikenessReviewError("P1 review manifest format/version mismatch")
        _strict_v1(review_manifest.get("version"), label="P1 review manifest")
        manifest_sha = _sha(
            review_manifest.get("p1_likeness_review_manifest_sha256"),
            label="P1 likeness review manifest SHA-256",
        )
        if _digest(review_manifest, omit="p1_likeness_review_manifest_sha256") != manifest_sha:
            raise PhotorealP1LikenessReviewError("P1 likeness review manifest digest mismatch")
        if _sha(
            receipt.get("p1_likeness_review_manifest_sha256"),
            label="receipt review-manifest SHA-256",
        ) != manifest_sha:
            raise PhotorealP1LikenessReviewError("P1 likeness receipt targets different review manifest")
        manifest_pairs = review_manifest.get("pairs")
        if not isinstance(manifest_pairs, list) or not manifest_pairs:
            raise PhotorealP1LikenessReviewError("P1 review manifest contains no criterion pairs")
        expected_criteria = {
            _safe_criterion(item.get("criterion"))
            for item in manifest_pairs
            if isinstance(item, Mapping)
        }
        if len(expected_criteria) != len(manifest_pairs) or set(decisions) != expected_criteria:
            raise PhotorealP1LikenessReviewError(
                "P1 likeness receipt criterion universe differs from review manifest"
            )
        for field in ("performer_id", "selected_epoch_id", "teacher_input_sha256", "semantic_alignment_sha256", "p1_pairing_sha256"):
            if receipt.get(field) != review_manifest.get(field):
                raise PhotorealP1LikenessReviewError(f"P1 likeness receipt provenance mismatch: {field}")

    return dict(receipt)


def _parse_decisions(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise PhotorealP1LikenessReviewError("P1 decision must use CRITERION=pass|fail")
        criterion, decision = (part.strip() for part in value.split("=", 1))
        if not criterion or not decision or criterion in result:
            raise PhotorealP1LikenessReviewError("P1 decision is empty/duplicated")
        result[criterion] = decision
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and record the human P1 static-teacher likeness review without production activation."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--pairing", type=Path, required=True)
    prepare.add_argument("--teacher-output-root", type=Path, required=True)
    prepare.add_argument("--appearance-review-root", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--reuse-existing", action="store_true")

    record = sub.add_parser("record")
    record.add_argument("--review-root", type=Path, required=True)
    record.add_argument("--decision", action="append", default=[])
    record.add_argument("--reviewed-by", required=True)
    record.add_argument("--review-notes", required=True)
    record.add_argument("--confirm-review-complete", action="store_true")
    record.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            pairing = _read_json(args.pairing, label="P1 pairing receipt")
            result = build_likeness_review_pack(
                pairing,
                teacher_output_root=args.teacher_output_root,
                appearance_review_root=args.appearance_review_root,
                output_root=args.out,
                reuse_existing=args.reuse_existing,
            )
            print(
                json.dumps(
                    {
                        "status": "HUMAN_LIKENESS_REVIEW_REQUIRED",
                        "criterion_count": result["criterion_count"],
                        "review_index": str(args.out.expanduser().resolve() / "review-index.html"),
                        "p1_static_teacher_acceptance_authority": False,
                        "human_visual_likeness_acceptance": False,
                        "p2_animation_authorized": False,
                        "photoreal_acceptance_authority": False,
                        "production_activation": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 2

        review_root = args.review_root.expanduser().resolve()
        manifest = validate_likeness_review_pack(review_root)
        receipt = record_likeness_review(
            manifest,
            decisions=_parse_decisions(list(args.decision)),
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            confirm_review_complete=args.confirm_review_complete,
        )
        output = args.out.expanduser().resolve()
        if output.exists():
            raise PhotorealP1LikenessReviewError(f"P1 likeness review receipt already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": receipt["p1_static_teacher_status"].upper(),
                    "p1_static_teacher_acceptance_authority": receipt["p1_static_teacher_acceptance_authority"],
                    "human_visual_likeness_acceptance": receipt["human_visual_likeness_acceptance"],
                    "p2_animation_authorized": receipt["p2_animation_authorized"],
                    "photoreal_acceptance_authority": False,
                    "production_activation": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except PhotorealP1LikenessReviewError as exc:
        print(f"BodyRig P1 likeness review: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
