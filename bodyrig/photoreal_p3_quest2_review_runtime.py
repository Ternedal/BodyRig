from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_device_distillation_runner import (
    REQUIRED_STUDENT_COMPONENTS,
    _digest,
    _file_sha,
    _sha,
    _strict_v1,
    _text,
)
from .photoreal_p3_device_runtime_review_plan import (
    PhotorealP3DeviceRuntimeReviewPlanError,
    validate_device_runtime_review_plan,
)


FORMAT = "bodyrig-photoreal-p3-quest2-review-runtime-manifest"
VERSION = 1
WORKSPACE_FORMAT = "bodyrig-photoreal-p3-quest2-review-runtime-workspace"
WORKSPACE_VERSION = 1

EXPECTED_ARTIFACTS = {
    "student-runtime-package": ("student/avatar.vrm", "avatar.vrm"),
    "teacher-derived-basecolor": ("student/basecolor.png", "basecolor.png"),
    "quest2-modular-provenance": (
        "student/quest2-modular-provenance.json",
        "quest2-modular-provenance.json",
    ),
}


class PhotorealP3Quest2ReviewRuntimeError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3Quest2ReviewRuntimeError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3Quest2ReviewRuntimeError(
            f"{label} must be a JSON object"
        )
    return value


def _revision(value: Any) -> str:
    clean = _text(
        value,
        label="P3 Quest2 review BodyRig revision",
        maximum=40,
    ).lower()
    if len(clean) != 40 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review BodyRig revision is invalid"
        )
    return clean


def _artifact_map(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = plan.get("student_artifacts")
    if not isinstance(raw, list) or len(raw) != len(EXPECTED_ARTIFACTS):
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review requires the exact final three-artifact universe"
        )
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise PhotorealP3Quest2ReviewRuntimeError(
                "P3 Quest2 review artifact record is invalid"
            )
        kind = str(item.get("kind") or "")
        expected = EXPECTED_ARTIFACTS.get(kind)
        if expected is None or kind in result:
            raise PhotorealP3Quest2ReviewRuntimeError(
                "P3 Quest2 review artifact kind universe differs"
            )
        if item.get("relative_path") != expected[0]:
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 Quest2 review artifact path differs: {kind}"
            )
        size = item.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 Quest2 review artifact size is invalid: {kind}"
            )
        result[kind] = {
            "kind": kind,
            "relative_path": expected[0],
            "review_name": expected[1],
            "size_bytes": size,
            "sha256": _sha(
                item.get("sha256"),
                label=f"P3 Quest2 review artifact SHA-256: {kind}",
            ),
        }
    if set(result) != set(EXPECTED_ARTIFACTS):
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review final artifact universe is incomplete"
        )
    return result


def validate_review_manifest(
    value: Mapping[str, Any],
    *,
    workspace: str | Path,
) -> dict[str, Any]:
    expected_fields = {
        "format",
        "version",
        "bodyrig_revision",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_execution_receipt_sha256",
        "p3_device_runtime_review_plan_sha256",
        "target_device_family",
        "target_device_model",
        "student_representation",
        "student_components",
        "avatar",
        "avatar_sha256",
        "basecolor",
        "basecolor_sha256",
        "provenance",
        "provenance_sha256",
        "physical_review_only",
        "comparison_only",
        "physical_device_evidence_present",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
    }
    if set(value) != expected_fields or value.get("format") != FORMAT:
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review manifest fields/format mismatch"
        )
    try:
        _strict_v1(value.get("version"), label="P3 Quest2 review manifest")
    except Exception as exc:
        raise PhotorealP3Quest2ReviewRuntimeError(str(exc)) from exc
    if value.get("version") != VERSION:
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review manifest version mismatch"
        )

    _revision(value.get("bodyrig_revision"))
    _text(value.get("performer_id"), label="P3 Quest2 review performer", maximum=256)
    _text(value.get("selected_epoch_id"), label="P3 Quest2 review epoch", maximum=256)
    for field in (
        "teacher_input_sha256",
        "p3_device_distillation_plan_sha256",
        "p3_device_distillation_execution_receipt_sha256",
        "p3_device_runtime_review_plan_sha256",
        "avatar_sha256",
        "basecolor_sha256",
        "provenance_sha256",
    ):
        _sha(value.get(field), label=f"P3 Quest2 review {field}")

    if (
        value.get("target_device_family") != "meta-quest"
        or value.get("target_device_model") != "quest-2"
        or value.get("student_representation") != "skinned-mesh-pbr"
        or value.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS)
    ):
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review target/student contract mismatch"
        )
    for field, expected in (
        ("avatar", "avatar.vrm"),
        ("basecolor", "basecolor.png"),
        ("provenance", "quest2-modular-provenance.json"),
        ("physical_review_only", True),
        ("comparison_only", True),
        ("physical_device_evidence_present", False),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) != expected:
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 Quest2 review manifest boundary mismatch: {field}"
            )

    root = Path(workspace).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review workspace is missing/not regular"
        )
    for name_field, sha_field in (
        ("avatar", "avatar_sha256"),
        ("basecolor", "basecolor_sha256"),
        ("provenance", "provenance_sha256"),
    ):
        name = str(value[name_field])
        path = (root / name).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 Quest2 review payload escaped workspace: {name}"
            ) from exc
        if not path.is_file() or path.is_symlink():
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 Quest2 review payload is missing/not regular: {name}"
            )
        if _file_sha(path) != value[sha_field]:
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 Quest2 review payload bytes drifted: {name}"
            )

    actual = {
        path.name
        for path in root.iterdir()
        if path.is_file()
    }
    expected_actual = {
        "p3-quest2-review-manifest.json",
        "avatar.vrm",
        "basecolor.png",
        "quest2-modular-provenance.json",
    }
    complete_actual = expected_actual | {
        "p3-quest2-review-runtime-receipt.json"
    }
    if actual not in (expected_actual, complete_actual):
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 review workspace file universe differs"
        )
    return dict(value)


def materialize_review_runtime(
    runtime_review_plan: Mapping[str, Any],
    *,
    final_output_root: str | Path,
    workspace: str | Path,
    bodyrig_revision: str,
) -> dict[str, Any]:
    try:
        plan = validate_device_runtime_review_plan(runtime_review_plan)
    except PhotorealP3DeviceRuntimeReviewPlanError as exc:
        raise PhotorealP3Quest2ReviewRuntimeError(str(exc)) from exc

    revision = _revision(bodyrig_revision)
    if (
        plan.get("target_device_family") != "meta-quest"
        or plan.get("target_device_model") != "quest-2"
        or plan.get("student_representation") != "skinned-mesh-pbr"
        or plan.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS)
        or plan.get("runtime_review_ready") is not True
        or plan.get("physical_device_evidence_present") is not False
        or plan.get("runtime_acceptance_authority") is not False
        or plan.get("photoreal_acceptance_authority") is not False
        or plan.get("production_activation") is not False
    ):
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 Quest2 runtime-review plan crossed/failed review-only boundary"
        )

    source_root = Path(final_output_root).expanduser().resolve()
    if not source_root.is_dir() or source_root.is_symlink():
        raise PhotorealP3Quest2ReviewRuntimeError(
            "P3 final output root is missing/not regular"
        )
    root = Path(workspace).expanduser().resolve()
    if root.exists():
        raise PhotorealP3Quest2ReviewRuntimeError(
            f"P3 Quest2 review workspace already exists: {root}"
        )
    root.mkdir(parents=True)

    artifacts = _artifact_map(plan)
    copied: dict[str, str] = {}
    for record in artifacts.values():
        source = (source_root / record["relative_path"]).resolve()
        try:
            source.relative_to(source_root)
        except ValueError as exc:
            raise PhotorealP3Quest2ReviewRuntimeError(
                "P3 final student artifact escaped output root"
            ) from exc
        if (
            not source.is_file()
            or source.is_symlink()
            or source.stat().st_size != record["size_bytes"]
            or _file_sha(source) != record["sha256"]
        ):
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 final student artifact bytes drifted: {record['kind']}"
            )
        destination = root / record["review_name"]
        shutil.copyfile(source, destination)
        observed = _file_sha(destination)
        if observed != record["sha256"]:
            raise PhotorealP3Quest2ReviewRuntimeError(
                f"P3 Quest2 review copy differs: {record['kind']}"
            )
        copied[record["kind"]] = observed

    manifest: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": revision,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "p3_device_distillation_plan_sha256": plan[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_execution_receipt_sha256": plan[
            "p3_device_distillation_execution_receipt_sha256"
        ],
        "p3_device_runtime_review_plan_sha256": plan[
            "p3_device_runtime_review_plan_sha256"
        ],
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "avatar": "avatar.vrm",
        "avatar_sha256": copied["student-runtime-package"],
        "basecolor": "basecolor.png",
        "basecolor_sha256": copied["teacher-derived-basecolor"],
        "provenance": "quest2-modular-provenance.json",
        "provenance_sha256": copied["quest2-modular-provenance"],
        "physical_review_only": True,
        "comparison_only": True,
        "physical_device_evidence_present": False,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    manifest_path = root / "p3-quest2-review-manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    validated = validate_review_manifest(manifest, workspace=root)

    receipt: dict[str, Any] = {
        "format": WORKSPACE_FORMAT,
        "version": WORKSPACE_VERSION,
        "bodyrig_revision": revision,
        "p3_device_runtime_review_plan_sha256": plan[
            "p3_device_runtime_review_plan_sha256"
        ],
        "review_manifest_sha256": _file_sha(manifest_path),
        "avatar_sha256": manifest["avatar_sha256"],
        "basecolor_sha256": manifest["basecolor_sha256"],
        "provenance_sha256": manifest["provenance_sha256"],
        "artifact_bytes_verified_by_core": True,
        "physical_review_only": True,
        "comparison_only": True,
        "physical_device_evidence_present": False,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p3_quest2_review_runtime_workspace_sha256"] = _digest(
        receipt,
        omit="p3_quest2_review_runtime_workspace_sha256",
    )
    (root / "p3-quest2-review-runtime-receipt.json").write_text(
        json.dumps(
            receipt,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "manifest": validated,
        "receipt": receipt,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the final modular Quest2 student into a strict, "
            "review-only runtime workspace. This is not Gate A or production."
        )
    )
    parser.add_argument("--runtime-review-plan", type=Path, required=True)
    parser.add_argument("--final-output-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        result = materialize_review_runtime(
            _read_json(
                args.runtime_review_plan,
                label="P3 Quest2 runtime-review plan",
            ),
            final_output_root=args.final_output_root,
            workspace=args.workspace,
            bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, PhotorealP3Quest2ReviewRuntimeError) as exc:
        print(f"BodyRig P3 Quest2 review runtime: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_REVIEW_RUNTIME_READY",
                "review_manifest_sha256": result["receipt"][
                    "review_manifest_sha256"
                ],
                "artifact_bytes_verified_by_core": True,
                "physical_review_only": True,
                "runtime_acceptance_authority": False,
                "photoreal_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
