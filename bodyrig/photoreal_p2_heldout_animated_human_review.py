from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_p2_exavatar_heldout_evaluation_runner import (
    PhotorealP2ExAvatarHeldoutEvaluationRunnerError,
    validate_heldout_evaluation_receipt,
)
from .photoreal_p2_heldout_animated_review_plan import (
    REVIEW_DIMENSIONS,
    PhotorealP2HeldoutAnimatedReviewPlanError,
    revalidate_heldout_animated_review_plan,
    validate_heldout_animated_review_plan,
)


MANIFEST_FORMAT = "bodyrig-photoreal-p2-heldout-animated-human-review-manifest"
MANIFEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p2-heldout-animated-human-review"
RECEIPT_VERSION = 1

QUALITY_CHECKS = (
    "temporal_stability",
    "identity_stability_across_motion",
    "appearance_stability_across_motion",
    "geometry_stability_no_collapse",
    "no_visible_texture_swimming_or_flicker",
    "visually_coherent_motion_control",
)


class PhotorealP2HeldoutAnimatedHumanReviewError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"{label} format/version mismatch"
        )


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
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human-review artifact cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"required review file is missing/not regular: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_ref(value: Any) -> str:
    ref = _text(value, label="HELD-OUT source ref", maximum=64)
    if any(not (ch.isalnum() or ch in "._-") for ch in ref):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"HELD-OUT source ref is not filename-safe: {ref}"
        )
    return ref


def _safe_child(root: Path, relative: Any, *, label: str) -> Path:
    rel_text = _text(relative, label=label).replace("\\", "/")
    rel = Path(rel_text)
    first = rel_text.split("/", 1)[0]
    if rel.is_absolute() or ".." in rel.parts or ":" in first:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(f"{label} escapes review root")
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"{label} escapes review root"
        ) from exc
    return target


def _evaluation_workspace_map(
    evaluation_workspaces: Sequence[str | Path],
) -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for workspace in evaluation_workspaces:
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir() or root.is_symlink():
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"HELD-OUT evaluation workspace is missing/not regular: {root}"
            )
        receipt_raw = _read_json(
            root / "heldout-evaluation-execution-receipt.json",
            label="HELD-OUT evaluation execution receipt",
        )
        try:
            receipt = validate_heldout_evaluation_receipt(receipt_raw)
        except PhotorealP2ExAvatarHeldoutEvaluationRunnerError as exc:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"HELD-OUT evaluation receipt strict readback failed: {exc}"
            ) from exc
        ref = _safe_ref(receipt.get("held_out_source_ref"))
        if ref in result:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "animated human review repeats a HELD-OUT evaluation source"
            )
        result[ref] = (root, receipt)
    return result


def _plan_evidence_by_ref(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    selections = plan.get("selections")
    if not isinstance(selections, list):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "animated review plan selection universe is invalid"
        )
    for raw in selections:
        if not isinstance(raw, Mapping):
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "animated review plan selection is invalid"
            )
        ref = _safe_ref(raw.get("held_out_source_ref"))
        normalized = {
            "heldout_evaluation_execution_receipt_sha256": _sha(
                raw.get("heldout_evaluation_execution_receipt_sha256"),
                label="HELD-OUT evaluation receipt SHA-256",
            ),
            "review_artifact_size_bytes": raw.get("review_artifact_size_bytes"),
            "review_artifact_sha256": _sha(
                raw.get("review_artifact_sha256"),
                label="HELD-OUT review video SHA-256",
            ),
        }
        if ref in result and result[ref] != normalized:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "animated review plan has inconsistent evidence for one HELD-OUT source"
            )
        result[ref] = normalized
    return result


def _write_review_html(manifest: Mapping[str, Any], output: Path) -> None:
    rows: list[str] = []
    by_ref = {
        item["held_out_source_ref"]: item
        for item in manifest["evidence_sources"]
    }
    for mapping in manifest["dimension_evidence"]:
        dimension = html.escape(str(mapping["dimension"]))
        ref = str(mapping["held_out_source_ref"])
        evidence = by_ref[ref]
        video = html.escape(str(evidence["copy_relative_path"]))
        rows.append(
            "<section>"
            f"<h2>{dimension}</h2>"
            f"<p>HELD-OUT source: <code>{html.escape(ref)}</code></p>"
            f"<video controls preload=\"metadata\" src=\"{video}\"></video>"
            "<p class=\"layout\">ExAvatar review layout: real HELD-OUT reference | rendered SMPL-X mesh | frozen teacher render.</p>"
            "<p class=\"decision\">Human decision required: PASS or FAIL for this dimension.</p>"
            "</section>"
        )

    quality = "".join(
        f"<li><code>{html.escape(item)}</code> — PASS or FAIL required</li>"
        for item in QUALITY_CHECKS
    )
    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>BodyRig P2 animated teacher review</title>
<style>
body{font-family:system-ui,sans-serif;background:#0f1115;color:#f3f5f7;margin:2rem;line-height:1.45}
.notice{border:1px solid #8b6f2d;background:#241e0f;padding:1rem;margin:1rem 0 2rem}
section{border-top:1px solid #363a43;padding:1.5rem 0 2.5rem}
video{display:block;max-width:100%;width:1100px;background:#000;border:1px solid #343944}
code{background:#1b1f27;padding:.1rem .3rem}.decision{font-weight:700}.layout{color:#c8ccd4}
</style></head><body>
<h1>BodyRig Photoreal V2 — P2 HELD-OUT animated teacher review</h1>
<div class="notice"><strong>Human visual authority required.</strong> Every selected video is generated by the frozen accepted teacher from HELD-OUT EVALUATION motion. Machine execution success is not a visual PASS. Review every motion dimension and every quality check. Any FAIL keeps P2 acceptance and P3/Quest distillation closed.</div>
""" + "\n".join(rows) + f"""
<h2>Required quality checklist</h2><ul>{quality}</ul>
</body></html>
"""
    output.write_text(document, encoding="utf-8", newline="\n")


def build_animated_human_review_pack(
    review_plan: Mapping[str, Any],
    *,
    evaluation_workspaces: Sequence[str | Path],
    output_root: str | Path,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    try:
        plan = revalidate_heldout_animated_review_plan(
            review_plan,
            evaluation_workspaces=evaluation_workspaces,
        )
    except PhotorealP2HeldoutAnimatedReviewPlanError as exc:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"animated review plan strict evidence readback failed: {exc}"
        ) from exc

    workspaces = _evaluation_workspace_map(evaluation_workspaces)
    planned = _plan_evidence_by_ref(plan)
    if set(workspaces) != set(planned):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "animated human review workspace universe differs from selected evidence universe"
        )

    output = Path(output_root).expanduser().resolve()
    if output.exists():
        if reuse_existing:
            return validate_animated_human_review_pack(
                output,
                expected_review_plan=plan,
            )
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"P2 animated human review pack already exists: {output}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        evidence_sources: list[dict[str, Any]] = []
        for ref in sorted(planned):
            root, receipt = workspaces[ref]
            expected = planned[ref]
            receipt_sha = _sha(
                receipt.get(
                    "p2_exavatar_heldout_evaluation_execution_receipt_sha256"
                ),
                label="HELD-OUT evaluation execution receipt SHA-256",
            )
            if receipt_sha != expected[
                "heldout_evaluation_execution_receipt_sha256"
            ]:
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"review plan targets a different HELD-OUT execution receipt: {ref}"
                )
            source = root / "output" / "review" / "heldout-animation.mp4"
            observed_sha = _file_sha(source)
            observed_size = source.stat().st_size
            if (
                observed_sha != expected["review_artifact_sha256"]
                or observed_size != expected["review_artifact_size_bytes"]
            ):
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"HELD-OUT review video bytes changed before human review: {ref}"
                )
            relative = f"evidence/{ref}.mp4"
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied_sha = _file_sha(target)
            if copied_sha != observed_sha:
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"HELD-OUT review video copy SHA mismatch: {ref}"
                )
            evidence_sources.append(
                {
                    "held_out_source_ref": ref,
                    "heldout_evaluation_execution_receipt_sha256": receipt_sha,
                    "source_video_size_bytes": observed_size,
                    "source_video_sha256": observed_sha,
                    "copy_relative_path": relative,
                    "copy_sha256": copied_sha,
                }
            )

        dimension_evidence = [
            {
                "dimension": item["dimension"],
                "held_out_source_ref": item["held_out_source_ref"],
            }
            for item in plan["selections"]
        ]
        manifest: dict[str, Any] = {
            "format": MANIFEST_FORMAT,
            "version": MANIFEST_VERSION,
            "performer_id": plan["performer_id"],
            "selected_epoch_id": plan["selected_epoch_id"],
            "teacher_input_sha256": plan["teacher_input_sha256"],
            "p2_animation_plan_sha256": plan["p2_animation_plan_sha256"],
            "p2_exavatar_animation_execution_input_sha256": plan[
                "p2_exavatar_animation_execution_input_sha256"
            ],
            "train_animation_execution_receipt_sha256": plan[
                "train_animation_execution_receipt_sha256"
            ],
            "consumed_checkpoint_sha256": plan["consumed_checkpoint_sha256"],
            "p2_heldout_animated_review_plan_sha256": plan[
                "p2_heldout_animated_review_plan_sha256"
            ],
            "review_dimensions": list(REVIEW_DIMENSIONS),
            "quality_checks": list(QUALITY_CHECKS),
            "evidence_sources": evidence_sources,
            "evidence_source_count": len(evidence_sources),
            "dimension_evidence": dimension_evidence,
            "dimension_evidence_count": len(dimension_evidence),
            "human_animated_visual_acceptance_required": True,
            "human_animated_review_complete": False,
            "p2_animated_teacher_acceptance_authority": False,
            "p3_device_distillation_authorized": False,
            "quest_distillation_authorized": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        html_path = stage / "review-index.html"
        _write_review_html(manifest, html_path)
        manifest["review_index_sha256"] = _file_sha(html_path)
        manifest["p2_heldout_animated_human_review_manifest_sha256"] = _digest(
            manifest,
            omit="p2_heldout_animated_human_review_manifest_sha256",
        )
        (stage / "p2-heldout-animated-human-review-manifest.json").write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(stage, output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return validate_animated_human_review_pack(
        output,
        expected_review_plan=plan,
    )


def validate_animated_human_review_pack(
    output_root: str | Path,
    *,
    expected_review_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(output_root).expanduser().resolve()
    manifest = _read_json(
        root / "p2-heldout-animated-human-review-manifest.json",
        label="P2 animated human review manifest",
    )
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "consumed_checkpoint_sha256",
        "p2_heldout_animated_review_plan_sha256",
        "review_dimensions",
        "quality_checks",
        "evidence_sources",
        "evidence_source_count",
        "dimension_evidence",
        "dimension_evidence_count",
        "human_animated_visual_acceptance_required",
        "human_animated_review_complete",
        "p2_animated_teacher_acceptance_authority",
        "p3_device_distillation_authorized",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "review_index_sha256",
        "p2_heldout_animated_human_review_manifest_sha256",
    }
    if set(manifest) != expected_fields:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review manifest fields must match v1 exactly"
        )
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review manifest format/version mismatch"
        )
    _strict_v1(manifest.get("version"), label="P2 animated human review manifest")
    claimed = _sha(
        manifest.get("p2_heldout_animated_human_review_manifest_sha256"),
        label="P2 animated human review manifest SHA-256",
    )
    if _digest(
        manifest,
        omit="p2_heldout_animated_human_review_manifest_sha256",
    ) != claimed:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review manifest digest mismatch"
        )
    if _sha(
        manifest.get("review_index_sha256"),
        label="P2 animated human review HTML SHA-256",
    ) != _file_sha(root / "review-index.html"):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review HTML bytes changed"
        )
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "consumed_checkpoint_sha256",
        "p2_heldout_animated_review_plan_sha256",
    ):
        _sha(manifest.get(field), label=f"P2 animated human review manifest {field}")
    _text(manifest.get("performer_id"), label="P2 review performer", maximum=256)
    _text(manifest.get("selected_epoch_id"), label="P2 review epoch", maximum=256)

    if manifest.get("review_dimensions") != list(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review dimension universe mismatch"
        )
    if manifest.get("quality_checks") != list(QUALITY_CHECKS):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review quality-check universe mismatch"
        )

    sources = manifest.get("evidence_sources")
    source_count = manifest.get("evidence_source_count")
    if (
        not isinstance(sources, list)
        or not sources
        or isinstance(source_count, bool)
        or not isinstance(source_count, int)
        or source_count != len(sources)
    ):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review evidence source count mismatch"
        )
    source_refs: set[str] = set()
    source_hashes: dict[str, str] = {}
    for raw in sources:
        if not isinstance(raw, Mapping) or set(raw) != {
            "held_out_source_ref",
            "heldout_evaluation_execution_receipt_sha256",
            "source_video_size_bytes",
            "source_video_sha256",
            "copy_relative_path",
            "copy_sha256",
        }:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review evidence fields must match v1 exactly"
            )
        ref = _safe_ref(raw.get("held_out_source_ref"))
        if ref in source_refs:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review repeats an evidence source"
            )
        source_refs.add(ref)
        _sha(
            raw.get("heldout_evaluation_execution_receipt_sha256"),
            label="P2 review evidence receipt SHA-256",
        )
        size = raw.get("source_video_size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review source video size is invalid"
            )
        source_sha = _sha(
            raw.get("source_video_sha256"),
            label="P2 review source video SHA-256",
        )
        copy_sha = _sha(
            raw.get("copy_sha256"),
            label="P2 review copied video SHA-256",
        )
        if copy_sha != source_sha:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review copy/source SHA mismatch"
            )
        expected_relative = f"evidence/{ref}.mp4"
        if raw.get("copy_relative_path") != expected_relative:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review copy path is not canonical"
            )
        copy_path = _safe_child(
            root,
            expected_relative,
            label="P2 animated human review copied video path",
        )
        if copy_path.stat().st_size != size or _file_sha(copy_path) != copy_sha:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"P2 animated human review copied video bytes changed: {ref}"
            )
        source_hashes[ref] = source_sha

    mappings = manifest.get("dimension_evidence")
    mapping_count = manifest.get("dimension_evidence_count")
    if (
        not isinstance(mappings, list)
        or isinstance(mapping_count, bool)
        or not isinstance(mapping_count, int)
        or mapping_count != len(REVIEW_DIMENSIONS)
        or len(mappings) != mapping_count
    ):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review dimension evidence count mismatch"
        )
    dimensions: list[str] = []
    for raw in mappings:
        if not isinstance(raw, Mapping) or set(raw) != {
            "dimension",
            "held_out_source_ref",
        }:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review dimension evidence fields must match v1 exactly"
            )
        dimension = _text(
            raw.get("dimension"),
            label="P2 animated human review dimension",
            maximum=80,
        )
        ref = _safe_ref(raw.get("held_out_source_ref"))
        if ref not in source_refs:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review dimension references unknown evidence"
            )
        dimensions.append(dimension)
    if dimensions != list(REVIEW_DIMENSIONS):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review dimension evidence is not canonical/complete"
        )

    for field, expected in (
        ("human_animated_visual_acceptance_required", True),
        ("human_animated_review_complete", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("p3_device_distillation_authorized", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"P2 animated human review manifest authority mismatch: {field}"
            )

    if expected_review_plan is not None:
        try:
            plan = validate_heldout_animated_review_plan(expected_review_plan)
        except PhotorealP2HeldoutAnimatedReviewPlanError as exc:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(str(exc)) from exc
        if manifest["p2_heldout_animated_review_plan_sha256"] != plan[
            "p2_heldout_animated_review_plan_sha256"
        ]:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review pack targets a different review plan"
            )
        for field in (
            "performer_id",
            "selected_epoch_id",
            "teacher_input_sha256",
            "p2_animation_plan_sha256",
            "p2_exavatar_animation_execution_input_sha256",
            "train_animation_execution_receipt_sha256",
            "consumed_checkpoint_sha256",
        ):
            if manifest.get(field) != plan.get(field):
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"P2 animated human review plan provenance mismatch: {field}"
                )
        planned_map = {
            item["dimension"]: (
                item["held_out_source_ref"],
                item["review_artifact_sha256"],
            )
            for item in plan["selections"]
        }
        for mapping in mappings:
            dimension = mapping["dimension"]
            ref = mapping["held_out_source_ref"]
            if planned_map.get(dimension) != (ref, source_hashes[ref]):
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"P2 animated human review evidence differs from review plan: {dimension}"
                )
    return dict(manifest)


def _normalize_decisions(
    decisions: Mapping[str, str],
    universe: Sequence[str],
    *,
    label: str,
) -> list[dict[str, str]]:
    if set(decisions) != set(universe):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            f"{label} must decide PASS/FAIL for every required item exactly once"
        )
    result: list[dict[str, str]] = []
    for item in universe:
        decision = _text(
            decisions.get(item),
            label=f"{label} decision {item}",
            maximum=16,
        ).lower()
        if decision not in {"pass", "fail"}:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"{label} decision must be pass/fail: {item}"
            )
        result.append({"criterion": item, "decision": decision})
    return result


def record_animated_human_review(
    manifest: Mapping[str, Any],
    *,
    dimension_decisions: Mapping[str, str],
    quality_decisions: Mapping[str, str],
    reviewed_by: str,
    review_notes: str,
    confirm_review_complete: bool,
) -> dict[str, Any]:
    if confirm_review_complete is not True:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "explicit human P2 animated review completion confirmation is required"
        )
    if manifest.get("format") != MANIFEST_FORMAT:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review manifest format/version mismatch"
        )
    _strict_v1(manifest.get("version"), label="P2 animated human review manifest")
    manifest_sha = _sha(
        manifest.get("p2_heldout_animated_human_review_manifest_sha256"),
        label="P2 animated human review manifest SHA-256",
    )
    if _digest(
        manifest,
        omit="p2_heldout_animated_human_review_manifest_sha256",
    ) != manifest_sha:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review manifest digest mismatch"
        )
    for field, expected in (
        ("human_animated_visual_acceptance_required", True),
        ("human_animated_review_complete", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("p3_device_distillation_authorized", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if manifest.get(field) is not expected:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"P2 animated human review manifest authority mismatch: {field}"
            )

    dimensions = _normalize_decisions(
        dimension_decisions,
        REVIEW_DIMENSIONS,
        label="P2 animated review dimension",
    )
    quality = _normalize_decisions(
        quality_decisions,
        QUALITY_CHECKS,
        label="P2 animated review quality check",
    )
    reviewer = _text(reviewed_by, label="P2 animated review reviewer", maximum=256)
    if (
        not isinstance(review_notes, str)
        or not review_notes.strip()
        or len(review_notes) > 8192
    ):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated review notes are invalid"
        )

    all_pass = all(
        item["decision"] == "pass"
        for item in dimensions + quality
    )
    receipt: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": _text(
            manifest.get("performer_id"),
            label="P2 review performer",
            maximum=256,
        ),
        "selected_epoch_id": _text(
            manifest.get("selected_epoch_id"),
            label="P2 review epoch",
            maximum=256,
        ),
        "teacher_input_sha256": _sha(
            manifest.get("teacher_input_sha256"),
            label="teacher input SHA-256",
        ),
        "p2_animation_plan_sha256": _sha(
            manifest.get("p2_animation_plan_sha256"),
            label="P2 animation plan SHA-256",
        ),
        "p2_exavatar_animation_execution_input_sha256": _sha(
            manifest.get("p2_exavatar_animation_execution_input_sha256"),
            label="P2 ExAvatar execution input SHA-256",
        ),
        "train_animation_execution_receipt_sha256": _sha(
            manifest.get("train_animation_execution_receipt_sha256"),
            label="TRAIN animation execution receipt SHA-256",
        ),
        "consumed_checkpoint_sha256": _sha(
            manifest.get("consumed_checkpoint_sha256"),
            label="frozen checkpoint SHA-256",
        ),
        "p2_heldout_animated_review_plan_sha256": _sha(
            manifest.get("p2_heldout_animated_review_plan_sha256"),
            label="P2 held-out animated review plan SHA-256",
        ),
        "p2_heldout_animated_human_review_manifest_sha256": manifest_sha,
        "dimension_results": dimensions,
        "quality_results": quality,
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "human_animated_visual_acceptance_required": True,
        "human_animated_review_complete": True,
        "human_animated_review_status": "pass" if all_pass else "fail",
        "animated_teacher_photoreal_accepted": all_pass,
        "p2_animated_teacher_acceptance_authority": all_pass,
        "p3_device_distillation_authorized": all_pass,
        "quest_distillation_authorized": all_pass,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p2_heldout_animated_human_review_sha256"] = _digest(
        receipt,
        omit="p2_heldout_animated_human_review_sha256",
    )
    return validate_animated_human_review_receipt(
        receipt,
        review_manifest=manifest,
    )


def validate_animated_human_review_receipt(
    receipt: Mapping[str, Any],
    *,
    review_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "consumed_checkpoint_sha256",
        "p2_heldout_animated_review_plan_sha256",
        "p2_heldout_animated_human_review_manifest_sha256",
        "dimension_results",
        "quality_results",
        "reviewed_by",
        "review_notes",
        "human_animated_visual_acceptance_required",
        "human_animated_review_complete",
        "human_animated_review_status",
        "animated_teacher_photoreal_accepted",
        "p2_animated_teacher_acceptance_authority",
        "p3_device_distillation_authorized",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_heldout_animated_human_review_sha256",
    }
    if set(receipt) != expected_fields:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review receipt fields must match v1 exactly"
        )
    if receipt.get("format") != RECEIPT_FORMAT:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review receipt format/version mismatch"
        )
    _strict_v1(receipt.get("version"), label="P2 animated human review receipt")
    claimed = _sha(
        receipt.get("p2_heldout_animated_human_review_sha256"),
        label="P2 animated human review receipt SHA-256",
    )
    if _digest(
        receipt,
        omit="p2_heldout_animated_human_review_sha256",
    ) != claimed:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review receipt digest mismatch"
        )
    for field in (
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_exavatar_animation_execution_input_sha256",
        "train_animation_execution_receipt_sha256",
        "consumed_checkpoint_sha256",
        "p2_heldout_animated_review_plan_sha256",
        "p2_heldout_animated_human_review_manifest_sha256",
    ):
        _sha(receipt.get(field), label=f"P2 animated human review receipt {field}")

    def decision_map(raw_values: Any, universe: Sequence[str], label: str) -> dict[str, str]:
        if not isinstance(raw_values, list) or len(raw_values) != len(universe):
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"{label} result count mismatch"
            )
        result: dict[str, str] = {}
        for raw in raw_values:
            if not isinstance(raw, Mapping) or set(raw) != {"criterion", "decision"}:
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"{label} result fields must match v1 exactly"
                )
            criterion = _text(
                raw.get("criterion"),
                label=f"{label} criterion",
                maximum=80,
            )
            if criterion in result:
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"{label} repeats criterion"
                )
            decision = _text(
                raw.get("decision"),
                label=f"{label} decision",
                maximum=16,
            ).lower()
            if decision not in {"pass", "fail"}:
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"{label} decision must be pass/fail"
                )
            result[criterion] = decision
        if list(result) != list(universe):
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"{label} criterion universe/order mismatch"
            )
        return result

    dimension_results = decision_map(
        receipt.get("dimension_results"),
        REVIEW_DIMENSIONS,
        "P2 animated review dimension",
    )
    quality_results = decision_map(
        receipt.get("quality_results"),
        QUALITY_CHECKS,
        "P2 animated review quality",
    )
    all_pass = all(
        value == "pass"
        for value in list(dimension_results.values()) + list(quality_results.values())
    )
    status = _text(
        receipt.get("human_animated_review_status"),
        label="P2 animated review status",
        maximum=16,
    ).lower()
    if status not in {"pass", "fail"} or (status == "pass") is not all_pass:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated human review status does not match detailed decisions"
        )
    for field, expected in (
        ("human_animated_visual_acceptance_required", True),
        ("human_animated_review_complete", True),
        ("animated_teacher_photoreal_accepted", all_pass),
        ("p2_animated_teacher_acceptance_authority", all_pass),
        ("p3_device_distillation_authorized", all_pass),
        ("quest_distillation_authorized", all_pass),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not expected:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"P2 animated human review receipt authority mismatch: {field}"
            )
    _text(receipt.get("reviewed_by"), label="P2 animated review reviewer", maximum=256)
    notes = receipt.get("review_notes")
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 8192:
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P2 animated review receipt notes are invalid"
        )

    if review_manifest is not None:
        if review_manifest.get("format") != MANIFEST_FORMAT:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review manifest format/version mismatch"
            )
        manifest_sha = _sha(
            review_manifest.get(
                "p2_heldout_animated_human_review_manifest_sha256"
            ),
            label="P2 animated human review manifest SHA-256",
        )
        if _digest(
            review_manifest,
            omit="p2_heldout_animated_human_review_manifest_sha256",
        ) != manifest_sha:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review manifest digest mismatch"
            )
        if receipt[
            "p2_heldout_animated_human_review_manifest_sha256"
        ] != manifest_sha:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                "P2 animated human review receipt targets a different review manifest"
            )
        for field in (
            "performer_id",
            "selected_epoch_id",
            "teacher_input_sha256",
            "p2_animation_plan_sha256",
            "p2_exavatar_animation_execution_input_sha256",
            "train_animation_execution_receipt_sha256",
            "consumed_checkpoint_sha256",
            "p2_heldout_animated_review_plan_sha256",
        ):
            if receipt.get(field) != review_manifest.get(field):
                raise PhotorealP2HeldoutAnimatedHumanReviewError(
                    f"P2 animated human review receipt provenance mismatch: {field}"
                )
    return dict(receipt)


def require_p3_device_distillation_authority(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_animated_human_review_receipt(receipt)
    if (
        validated["human_animated_review_status"] != "pass"
        or validated["p2_animated_teacher_acceptance_authority"] is not True
        or validated["p3_device_distillation_authorized"] is not True
    ):
        raise PhotorealP2HeldoutAnimatedHumanReviewError(
            "P3 device distillation requires an exact human P2 animated-teacher PASS"
        )
    return validated


def _parse_decisions(values: Sequence[str], *, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"{label} must use NAME=pass|fail"
            )
        name, decision = (part.strip() for part in raw.split("=", 1))
        if not name or not decision or name in result:
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"{label} is empty/duplicated"
            )
        result[name] = decision
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and record explicit human P2 HELD-OUT animated-teacher review."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--review-plan", type=Path, required=True)
    prepare.add_argument(
        "--evaluation-workspace",
        type=Path,
        action="append",
        default=[],
    )
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--reuse-existing", action="store_true")

    record = sub.add_parser("record")
    record.add_argument("--review-root", type=Path, required=True)
    record.add_argument("--decision", action="append", default=[])
    record.add_argument("--quality-check", action="append", default=[])
    record.add_argument("--reviewed-by", required=True)
    record.add_argument("--review-notes", required=True)
    record.add_argument("--confirm-review-complete", action="store_true")
    record.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            plan = _read_json(args.review_plan, label="P2 HELD-OUT animated review plan")
            manifest = build_animated_human_review_pack(
                plan,
                evaluation_workspaces=args.evaluation_workspace,
                output_root=args.out,
                reuse_existing=args.reuse_existing,
            )
            print(
                json.dumps(
                    {
                        "status": "HUMAN_P2_ANIMATED_REVIEW_REQUIRED",
                        "review_index": str(
                            args.out.expanduser().resolve() / "review-index.html"
                        ),
                        "review_dimension_count": len(REVIEW_DIMENSIONS),
                        "quality_check_count": len(QUALITY_CHECKS),
                        "human_animated_review_complete": False,
                        "p2_animated_teacher_acceptance_authority": False,
                        "p3_device_distillation_authorized": False,
                        "production_activation": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 2

        review_root = args.review_root.expanduser().resolve()
        manifest = validate_animated_human_review_pack(review_root)
        receipt = record_animated_human_review(
            manifest,
            dimension_decisions=_parse_decisions(
                list(args.decision),
                label="P2 dimension decision",
            ),
            quality_decisions=_parse_decisions(
                list(args.quality_check),
                label="P2 quality decision",
            ),
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            confirm_review_complete=args.confirm_review_complete,
        )
        output = args.out.expanduser().resolve()
        if output.exists():
            raise PhotorealP2HeldoutAnimatedHumanReviewError(
                f"P2 animated human review receipt already exists: {output}"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                receipt,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": receipt["human_animated_review_status"].upper(),
                    "human_animated_review_complete": True,
                    "p2_animated_teacher_acceptance_authority": receipt[
                        "p2_animated_teacher_acceptance_authority"
                    ],
                    "p3_device_distillation_authorized": receipt[
                        "p3_device_distillation_authorized"
                    ],
                    "production_activation": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except PhotorealP2HeldoutAnimatedHumanReviewError as exc:
        print(f"BodyRig P2 animated human review: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
