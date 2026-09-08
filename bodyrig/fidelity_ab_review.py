from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fidelity_ab import FORMAT as AB_FORMAT, VERSION as AB_VERSION

FORMAT = "bodyrig-fidelity-ab-human-review"
VERSION = 1
SHA256_LEN = 64
REVISION_LEN = 40
CANONICAL_VIEWS = ("front-full", "three-quarter-full", "side-full", "face-front")
DECISIONS = ("left", "right", "tie", "reject-both")


class FidelityAbReviewError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FidelityAbReviewError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FidelityAbReviewError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityAbReviewError(f"{label} must be a JSON object")
    return value


def _need_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise FidelityAbReviewError(f"{label} is missing")
    normalized = value.strip().lower()
    if len(normalized) != SHA256_LEN or any(ch not in "0123456789abcdef" for ch in normalized):
        raise FidelityAbReviewError(f"{label} is not a canonical SHA-256")
    return normalized


def _need_revision(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise FidelityAbReviewError(f"{label} is missing")
    normalized = value.strip().lower()
    if len(normalized) != REVISION_LEN or any(ch not in "0123456789abcdef" for ch in normalized):
        raise FidelityAbReviewError(f"{label} is not a canonical Git revision")
    return normalized


def _validate_ab(path: Path) -> dict[str, Any]:
    evidence = _load_json(path, label="fidelity A/B evidence")
    if evidence.get("format") != AB_FORMAT or evidence.get("version") != AB_VERSION:
        raise FidelityAbReviewError("fidelity A/B evidence format/version mismatch")
    invariants = evidence.get("invariants")
    if not isinstance(invariants, dict) or invariants.get("clean_appearance_ab") is not True:
        raise FidelityAbReviewError("human A/B review requires a clean appearance-only machine PASS")
    if evidence.get("human_visual_authority_required") is not True:
        raise FidelityAbReviewError("fidelity A/B evidence does not require human visual authority")
    if evidence.get("comparison_only") is not True or evidence.get("production_activation") is not False:
        raise FidelityAbReviewError("fidelity A/B evidence crossed the comparison-only boundary")

    binding = evidence.get("revision_binding")
    if not isinstance(binding, dict) or binding.get("passed") is not True:
        raise FidelityAbReviewError("fidelity A/B evidence is not revision-bound")

    left = evidence.get("left")
    right = evidence.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise FidelityAbReviewError("fidelity A/B sides are missing")
    left_revision = _need_revision(left.get("builder_revision"), label="left builder revision")
    right_revision = _need_revision(right.get("builder_revision"), label="right builder revision")
    if _need_revision(binding.get("expected_left_builder_revision"), label="expected left builder revision") != left_revision:
        raise FidelityAbReviewError("left revision binding is inconsistent")
    if _need_revision(binding.get("expected_right_builder_revision"), label="expected right builder revision") != right_revision:
        raise FidelityAbReviewError("right revision binding is inconsistent")
    _need_sha(left.get("package_sha256"), label="left package SHA-256")
    _need_sha(right.get("package_sha256"), label="right package SHA-256")
    return evidence


def _validate_render_dir(path: Path, *, side: dict[str, Any], label: str) -> dict[str, str]:
    if not path.is_dir():
        raise FidelityAbReviewError(f"{label} render directory not found: {path}")
    comparison_path = path / "comparison-authority.json"
    render_set_path = path / "snapshots" / "fidelity-render-set.json"
    comparison = _load_json(comparison_path, label=f"{label} comparison authority")
    render_set = _load_json(render_set_path, label=f"{label} render set")

    package_sha = _need_sha(side.get("package_sha256"), label=f"{label} package SHA-256")
    if comparison.get("format") != "bodyrig-fidelity-comparison-authority" or comparison.get("version") != 1:
        raise FidelityAbReviewError(f"{label} comparison authority format/version mismatch")
    if comparison.get("comparison_only") is not True or comparison.get("production_activation") is not False:
        raise FidelityAbReviewError(f"{label} comparison authority crossed the comparison-only boundary")
    if _need_sha(comparison.get("package_sha256"), label=f"{label} comparison package SHA-256") != package_sha:
        raise FidelityAbReviewError(f"{label} comparison authority is bound to different package bytes")

    if render_set.get("format") != "bodyrig-fidelity-render-set" or render_set.get("version") != 1:
        raise FidelityAbReviewError(f"{label} render-set format/version mismatch")
    if render_set.get("semantics") != "visual-fidelity-not-identity-verification":
        raise FidelityAbReviewError(f"{label} render-set semantics mismatch")
    if _need_sha(render_set.get("package_sha256"), label=f"{label} render-set package SHA-256") != package_sha:
        raise FidelityAbReviewError(f"{label} render set is bound to different package bytes")

    snapshots = render_set.get("snapshots")
    if not isinstance(snapshots, list) or len(snapshots) != len(CANONICAL_VIEWS):
        raise FidelityAbReviewError(f"{label} render set must contain four canonical snapshots")
    actual_views: list[str] = []
    for entry in snapshots:
        if not isinstance(entry, dict):
            raise FidelityAbReviewError(f"{label} render-set snapshot is invalid")
        view = entry.get("view")
        if not isinstance(view, str):
            raise FidelityAbReviewError(f"{label} render-set snapshot view is invalid")
        actual_views.append(view)
        if entry.get("width") != 1024 or entry.get("height") != 1024:
            raise FidelityAbReviewError(f"{label} snapshot dimensions must be 1024x1024")
        filename = entry.get("file")
        if filename != f"{view}.png":
            raise FidelityAbReviewError(f"{label} snapshot filename/view binding mismatch")
        snapshot_path = path / "snapshots" / filename
        expected_sha = _need_sha(entry.get("sha256"), label=f"{label} {view} snapshot SHA-256")
        if _sha256_file(snapshot_path) != expected_sha:
            raise FidelityAbReviewError(f"{label} snapshot bytes changed after render capture: {view}")
    if tuple(actual_views) != CANONICAL_VIEWS:
        raise FidelityAbReviewError(f"{label} render-set canonical view order mismatch")

    return {
        "comparison_authority_sha256": _sha256_file(comparison_path),
        "render_set_sha256": _sha256_file(render_set_path),
    }


def build_review(
    *,
    ab_evidence: str | Path,
    left_render_dir: str | Path,
    right_render_dir: str | Path,
    decision: str,
    quality_note: str,
) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise FidelityAbReviewError(f"decision must be one of: {', '.join(DECISIONS)}")
    note = str(quality_note).strip()
    if not note or len(note) > 4000 or (note.startswith("<") and note.endswith(">")):
        raise FidelityAbReviewError("quality note must contain the operator's actual visual A/B assessment")

    ab_path = Path(ab_evidence).expanduser().resolve()
    evidence = _validate_ab(ab_path)
    left_render = _validate_render_dir(Path(left_render_dir).expanduser().resolve(), side=evidence["left"], label="left")
    right_render = _validate_render_dir(Path(right_render_dir).expanduser().resolve(), side=evidence["right"], label="right")

    preferred_side = decision if decision in {"left", "right"} else None
    return {
        "format": FORMAT,
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "decision": decision,
        "preferred_side": preferred_side,
        "quality_note": note,
        "ab_evidence_sha256": _sha256_file(ab_path),
        "left": {
            "package_sha256": _need_sha(evidence["left"].get("package_sha256"), label="left package SHA-256"),
            "builder_revision": _need_revision(evidence["left"].get("builder_revision"), label="left builder revision"),
            **left_render,
        },
        "right": {
            "package_sha256": _need_sha(evidence["right"].get("package_sha256"), label="right package SHA-256"),
            "builder_revision": _need_revision(evidence["right"].get("builder_revision"), label="right builder revision"),
            **right_render,
        },
        "clean_appearance_ab_verified": True,
        "human_visual_review_confirmed": True,
        "candidate_preference_authority": decision in {"left", "right"},
        "comparison_only": True,
        "physical_acceptance_authority": False,
        "production_activation": False,
    }


def _write_create_only(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FidelityAbReviewError(f"human A/B review output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a revision-bound human visual decision for one clean appearance A/B.")
    parser.add_argument("--ab-evidence", required=True)
    parser.add_argument("--left-render-dir", required=True)
    parser.add_argument("--right-render-dir", required=True)
    parser.add_argument("--decision", choices=DECISIONS, required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-visual-review", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    try:
        if not args.confirm_visual_review:
            raise FidelityAbReviewError("human A/B review requires explicit --confirm-visual-review")
        value = build_review(
            ab_evidence=args.ab_evidence,
            left_render_dir=args.left_render_dir,
            right_render_dir=args.right_render_dir,
            decision=args.decision,
            quality_note=args.quality_note,
        )
        _write_create_only(Path(args.out).expanduser().resolve(), value)
    except (FidelityAbReviewError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity A/B human review: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
