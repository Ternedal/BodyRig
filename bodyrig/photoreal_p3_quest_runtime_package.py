from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p3_device_distillation_runner import (
    REQUIRED_STUDENT_COMPONENTS,
    PhotorealP3DeviceDistillationRunnerError,
    validate_execution_receipt,
)


FORMAT = "bodyrig-photoreal-p3-quest-runtime-package"
VERSION = 1
BODYPRINT_FORMAT = "bodyrig-photoreal-p3-runtime-bodyprint"
BODYPRINT_VERSION = 1
RUNTIME_FORMAT = "bodyrig-runtime-assets"
RUNTIME_VERSION = 1
TARGET_MODEL = "quest-2"
STUDENT_REPRESENTATION = "skinned-mesh-pbr"
AVATAR_KIND = "quest2-vrm-student-runtime"
PROVENANCE_KIND = "exavatar-quest2-pbr-provenance"
PACKAGE_DOMAIN = b"bodyrig-photoreal-p3-quest2-runtime-package-v1\0"


class PhotorealP3QuestRuntimePackageError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP3QuestRuntimePackageError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP3QuestRuntimePackageError(
            f"{label} must be a JSON object"
        )
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP3QuestRuntimePackageError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealP3QuestRuntimePackageError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    clean = _text(value, label=label, maximum=64).lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealP3QuestRuntimePackageError(f"{label} is invalid")
    return clean


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP3QuestRuntimePackageError(
            f"{label} format/version mismatch"
        )
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP3QuestRuntimePackageError(
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
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime artifact cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotorealP3QuestRuntimePackageError(
            f"required runtime source is missing/not regular: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if (
        clean.startswith("/")
        or clean.startswith("../")
        or "/../" in f"/{clean}/"
        or ":" in first
    ):
        raise PhotorealP3QuestRuntimePackageError(
            f"{label} escapes its root"
        )
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealP3QuestRuntimePackageError(
            f"{label} escapes its root"
        ) from exc
    return clean, target


def _artifact_by_kind(
    execution: Mapping[str, Any],
    *,
    kind: str,
    student_output_root: Path,
) -> tuple[dict[str, Any], Path]:
    raw_artifacts = execution.get("student_artifacts")
    if not isinstance(raw_artifacts, list):
        raise PhotorealP3QuestRuntimePackageError(
            "P3 execution receipt student artifact universe is invalid"
        )
    matches = [
        item
        for item in raw_artifacts
        if isinstance(item, Mapping) and item.get("kind") == kind
    ]
    if len(matches) != 1:
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 execution receipt must contain exactly one student artifact kind: {kind}"
        )
    raw = matches[0]
    if set(raw) != {"kind", "relative_path", "size_bytes", "sha256"}:
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 student artifact fields are invalid: {kind}"
        )
    relative, path = _safe_child(
        student_output_root,
        raw.get("relative_path"),
        label=f"P3 {kind} path",
    )
    size = raw.get("size_bytes")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != size
    ):
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 {kind} size/path drifted"
        )
    expected_sha = _sha(
        raw.get("sha256"),
        label=f"P3 {kind} SHA-256",
    )
    if _file_sha(path) != expected_sha:
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 {kind} bytes drifted"
        )
    return {
        "kind": kind,
        "relative_path": relative,
        "size_bytes": size,
        "sha256": expected_sha,
    }, path


def _body_id(execution: Mapping[str, Any]) -> str:
    performer = _text(
        execution.get("performer_id"),
        label="P3 runtime performer",
        maximum=256,
    )
    epoch = _text(
        execution.get("selected_epoch_id"),
        label="P3 runtime epoch",
        maximum=256,
    )
    seed = hashlib.sha256(
        (
            performer
            + "\0"
            + epoch
            + "\0"
            + _sha(
                execution.get(
                    "p3_device_distillation_execution_receipt_sha256"
                ),
                label="P3 execution receipt SHA-256",
            )
        ).encode("utf-8")
    ).hexdigest()
    return "photoreal-p3-" + seed[:24]


def _package_sha(avatar_sha: str, bodyprint_sha: str) -> str:
    digest = hashlib.sha256()
    digest.update(PACKAGE_DOMAIN)
    digest.update(bytes.fromhex(avatar_sha))
    digest.update(bytes.fromhex(bodyprint_sha))
    return digest.hexdigest()


def build_quest_runtime_package(
    execution_receipt: Mapping[str, Any],
    *,
    student_output_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    try:
        execution = validate_execution_receipt(execution_receipt)
    except PhotorealP3DeviceDistillationRunnerError as exc:
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 execution receipt strict readback failed: {exc}"
        ) from exc

    if execution.get("target_model") != TARGET_MODEL:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package is pinned to Quest 2"
        )
    if execution.get("student_representation") != STUDENT_REPRESENTATION:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package requires the skinned-mesh-pbr student"
        )
    if execution.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS):
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package requires the canonical eye/hair components"
        )
    for field, expected in (
        ("distillation_complete", True),
        ("artifact_bytes_verified_by_core", True),
        ("staged_teacher_only", True),
        ("student_fidelity_claim_exceeds_teacher", False),
        ("human_runtime_visual_acceptance_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if execution.get(field) is not expected:
            raise PhotorealP3QuestRuntimePackageError(
                f"P3 execution authority mismatch before runtime packaging: {field}"
            )

    source_root = Path(student_output_root).expanduser().resolve()
    if not source_root.is_dir() or source_root.is_symlink():
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 student output root is missing/not regular: {source_root}"
        )
    avatar, avatar_source = _artifact_by_kind(
        execution,
        kind=AVATAR_KIND,
        student_output_root=source_root,
    )
    provenance, provenance_source = _artifact_by_kind(
        execution,
        kind=PROVENANCE_KIND,
        student_output_root=source_root,
    )

    output = Path(output_root).expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 Quest runtime output already exists: {output}"
        )
    output.mkdir(parents=True)

    try:
        avatar_target = output / "avatar.vrm"
        shutil.copy2(avatar_source, avatar_target)
        if (
            avatar_target.stat().st_size != avatar["size_bytes"]
            or _file_sha(avatar_target) != avatar["sha256"]
        ):
            raise PhotorealP3QuestRuntimePackageError(
                "P3 avatar bytes changed during runtime materialization"
            )

        source_provenance = _read_json(
            provenance_source,
            label="ExAvatar Quest2 PBR student provenance",
        )
        if (
            source_provenance.get("format")
            != "bodyrig-exavatar-quest2-pbr-student-provenance"
            or source_provenance.get("target_model") != TARGET_MODEL
            or source_provenance.get("student_representation")
            != STUDENT_REPRESENTATION
            or source_provenance.get("student_components")
            != list(REQUIRED_STUDENT_COMPONENTS)
        ):
            raise PhotorealP3QuestRuntimePackageError(
                "P3 student provenance does not match canonical Quest2 runtime semantics"
            )
        provenance_sha = _sha(
            source_provenance.get("student_provenance_sha256"),
            label="P3 student provenance SHA-256",
        )
        if _digest(
            source_provenance,
            omit="student_provenance_sha256",
        ) != provenance_sha:
            raise PhotorealP3QuestRuntimePackageError(
                "P3 student provenance digest mismatch"
            )
        if _file_sha(provenance_source) != provenance["sha256"]:
            raise PhotorealP3QuestRuntimePackageError(
                "P3 student provenance bytes changed before packaging"
            )

        body_id = _body_id(execution)
        bodyprint: dict[str, Any] = {
            "format": BODYPRINT_FORMAT,
            "version": BODYPRINT_VERSION,
            "body_id": body_id,
            "body_name": f"BodyRig Photoreal P3 performer {execution['performer_id']}",
            "performer_id": execution["performer_id"],
            "selected_epoch_id": execution["selected_epoch_id"],
            "target_device_family": "meta-quest",
            "target_device_model": TARGET_MODEL,
            "student_representation": STUDENT_REPRESENTATION,
            "student_components": list(REQUIRED_STUDENT_COMPONENTS),
            "executed_adapter": execution["adapter"],
            "executed_adapter_revision": execution["adapter_revision"],
            "p3_device_distillation_plan_sha256": execution[
                "p3_device_distillation_plan_sha256"
            ],
            "p3_device_distillation_request_sha256": execution[
                "p3_device_distillation_request_sha256"
            ],
            "p3_device_distillation_execution_receipt_sha256": execution[
                "p3_device_distillation_execution_receipt_sha256"
            ],
            "source_student_avatar_sha256": avatar["sha256"],
            "source_student_provenance_file_sha256": provenance["sha256"],
            "source_student_provenance_sha256": provenance_sha,
            "fidelity_delta_measurements": list(
                execution["fidelity_delta_measurements"]
            ),
            "physical_device_review_required": True,
            "runtime_acceptance_authority": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        bodyprint["p3_runtime_bodyprint_sha256"] = _digest(
            bodyprint,
            omit="p3_runtime_bodyprint_sha256",
        )
        bodyprint_path = output / "bodyprint.json"
        bodyprint_path.write_text(
            json.dumps(
                bodyprint,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        avatar_sha = _file_sha(avatar_target)
        bodyprint_file_sha = _file_sha(bodyprint_path)
        package_sha = _package_sha(avatar_sha, bodyprint_file_sha)

        runtime_manifest = {
            "format": RUNTIME_FORMAT,
            "version": RUNTIME_VERSION,
            "body_id": body_id,
            "body_name": bodyprint["body_name"],
            "package_sha256": package_sha,
            "avatar": "avatar.vrm",
            "avatar_sha256": avatar_sha,
            "bodyprint": "bodyprint.json",
            "bodyprint_sha256": bodyprint_file_sha,
            "payloads": ["avatar.vrm", "bodyprint.json"],
        }
        runtime_manifest_path = output / "runtime-manifest.json"
        runtime_manifest_path.write_text(
            json.dumps(
                runtime_manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )

        receipt: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "performer_id": execution["performer_id"],
            "selected_epoch_id": execution["selected_epoch_id"],
            "target_model": TARGET_MODEL,
            "student_representation": STUDENT_REPRESENTATION,
            "student_components": list(REQUIRED_STUDENT_COMPONENTS),
            "executed_adapter": execution["adapter"],
            "executed_adapter_revision": execution["adapter_revision"],
            "p3_device_distillation_execution_receipt_sha256": execution[
                "p3_device_distillation_execution_receipt_sha256"
            ],
            "source_student_avatar_sha256": avatar["sha256"],
            "source_student_provenance_file_sha256": provenance["sha256"],
            "runtime_package_sha256": package_sha,
            "runtime_manifest_sha256": _file_sha(runtime_manifest_path),
            "runtime_avatar_sha256": avatar_sha,
            "runtime_bodyprint_sha256": bodyprint_file_sha,
            "runtime_payloads": ["avatar.vrm", "bodyprint.json"],
            "runtime_loader_contract": "bodyrig-runtime-assets-v1",
            "student_bytes_reverified_before_copy": True,
            "runtime_bytes_reverified_after_copy": True,
            "physical_device_review_required": True,
            "runtime_acceptance_authority": False,
            "photoreal_acceptance_authority": False,
            "production_activation": False,
        }
        receipt["p3_quest_runtime_package_receipt_sha256"] = _digest(
            receipt,
            omit="p3_quest_runtime_package_receipt_sha256",
        )
        receipt_path = output / "p3-quest-runtime-package-receipt.json"
        receipt_path.write_text(
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
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise

    return validate_quest_runtime_package(output)


def validate_quest_runtime_package(output_root: str | Path) -> dict[str, Any]:
    root = Path(output_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise PhotorealP3QuestRuntimePackageError(
            f"P3 Quest runtime root is missing/not regular: {root}"
        )
    manifest = _read_json(
        root / "runtime-manifest.json",
        label="P3 Quest runtime manifest",
    )
    if set(manifest) != {
        "format",
        "version",
        "body_id",
        "body_name",
        "package_sha256",
        "avatar",
        "avatar_sha256",
        "bodyprint",
        "bodyprint_sha256",
        "payloads",
    }:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime manifest fields must match renderer v1 exactly"
        )
    if manifest.get("format") != RUNTIME_FORMAT:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime manifest format mismatch"
        )
    _strict_v1(manifest.get("version"), label="P3 Quest runtime manifest")
    if manifest.get("avatar") != "avatar.vrm" or manifest.get("bodyprint") != "bodyprint.json":
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime payload paths are not canonical"
        )
    if manifest.get("payloads") != ["avatar.vrm", "bodyprint.json"]:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime payload universe is not canonical"
        )
    avatar = root / "avatar.vrm"
    bodyprint_path = root / "bodyprint.json"
    avatar_sha = _sha(
        manifest.get("avatar_sha256"),
        label="P3 Quest runtime avatar SHA-256",
    )
    bodyprint_sha = _sha(
        manifest.get("bodyprint_sha256"),
        label="P3 Quest runtime bodyprint SHA-256",
    )
    if _file_sha(avatar) != avatar_sha or _file_sha(bodyprint_path) != bodyprint_sha:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime payload bytes differ from runtime manifest"
        )
    package_sha = _sha(
        manifest.get("package_sha256"),
        label="P3 Quest runtime package SHA-256",
    )
    if _package_sha(avatar_sha, bodyprint_sha) != package_sha:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package digest mismatch"
        )

    bodyprint = _read_json(bodyprint_path, label="P3 Quest runtime bodyprint")
    if bodyprint.get("format") != BODYPRINT_FORMAT:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime bodyprint format mismatch"
        )
    _strict_v1(bodyprint.get("version"), label="P3 Quest runtime bodyprint")
    claimed_bodyprint = _sha(
        bodyprint.get("p3_runtime_bodyprint_sha256"),
        label="P3 runtime bodyprint content SHA-256",
    )
    if _digest(bodyprint, omit="p3_runtime_bodyprint_sha256") != claimed_bodyprint:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime bodyprint digest mismatch"
        )
    if (
        bodyprint.get("target_device_family") != "meta-quest"
        or bodyprint.get("target_device_model") != TARGET_MODEL
        or bodyprint.get("student_representation") != STUDENT_REPRESENTATION
        or bodyprint.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS)
    ):
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime bodyprint semantics mismatch"
        )
    for field, expected in (
        ("physical_device_review_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if bodyprint.get(field) is not expected:
            raise PhotorealP3QuestRuntimePackageError(
                f"P3 Quest runtime bodyprint authority mismatch: {field}"
            )

    receipt = _read_json(
        root / "p3-quest-runtime-package-receipt.json",
        label="P3 Quest runtime package receipt",
    )
    expected_receipt_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "target_model",
        "student_representation",
        "student_components",
        "executed_adapter",
        "executed_adapter_revision",
        "p3_device_distillation_execution_receipt_sha256",
        "source_student_avatar_sha256",
        "source_student_provenance_file_sha256",
        "runtime_package_sha256",
        "runtime_manifest_sha256",
        "runtime_avatar_sha256",
        "runtime_bodyprint_sha256",
        "runtime_payloads",
        "runtime_loader_contract",
        "student_bytes_reverified_before_copy",
        "runtime_bytes_reverified_after_copy",
        "physical_device_review_required",
        "runtime_acceptance_authority",
        "photoreal_acceptance_authority",
        "production_activation",
        "p3_quest_runtime_package_receipt_sha256",
    }
    if set(receipt) != expected_receipt_fields or receipt.get("format") != FORMAT:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package receipt fields/format mismatch"
        )
    _strict_v1(receipt.get("version"), label="P3 Quest runtime package receipt")
    for field in (
        "executed_adapter_revision",
        "p3_device_distillation_execution_receipt_sha256",
        "source_student_avatar_sha256",
        "source_student_provenance_file_sha256",
        "runtime_package_sha256",
        "runtime_manifest_sha256",
        "runtime_avatar_sha256",
        "runtime_bodyprint_sha256",
    ):
        _sha(receipt.get(field), label=f"P3 Quest runtime package receipt {field}")
    if (
        receipt.get("target_model") != TARGET_MODEL
        or receipt.get("student_representation") != STUDENT_REPRESENTATION
        or receipt.get("student_components") != list(REQUIRED_STUDENT_COMPONENTS)
        or receipt.get("runtime_payloads") != ["avatar.vrm", "bodyprint.json"]
        or receipt.get("runtime_loader_contract") != "bodyrig-runtime-assets-v1"
    ):
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package receipt semantics mismatch"
        )
    if receipt.get("runtime_package_sha256") != package_sha:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package receipt package digest mismatch"
        )
    if receipt.get("runtime_manifest_sha256") != _file_sha(root / "runtime-manifest.json"):
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package receipt manifest digest mismatch"
        )
    if (
        receipt.get("runtime_avatar_sha256") != avatar_sha
        or receipt.get("runtime_bodyprint_sha256") != bodyprint_sha
    ):
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package receipt payload digest mismatch"
        )
    for field, expected in (
        ("student_bytes_reverified_before_copy", True),
        ("runtime_bytes_reverified_after_copy", True),
        ("physical_device_review_required", True),
        ("runtime_acceptance_authority", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not expected:
            raise PhotorealP3QuestRuntimePackageError(
                f"P3 Quest runtime package receipt authority mismatch: {field}"
            )
    claimed = _sha(
        receipt.get("p3_quest_runtime_package_receipt_sha256"),
        label="P3 Quest runtime package receipt SHA-256",
    )
    if _digest(
        receipt,
        omit="p3_quest_runtime_package_receipt_sha256",
    ) != claimed:
        raise PhotorealP3QuestRuntimePackageError(
            "P3 Quest runtime package receipt digest mismatch"
        )
    return dict(receipt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize an exact BodyRig reference-renderer runtime from the "
            "core-owned ExAvatar Quest2 PBR student execution receipt."
        )
    )
    parser.add_argument("--execution-receipt", type=Path, required=True)
    parser.add_argument("--student-output-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_quest_runtime_package(
            _read_json(
                args.execution_receipt,
                label="P3 distillation execution receipt",
            ),
            student_output_root=args.student_output_root,
            output_root=args.out,
        )
    except PhotorealP3QuestRuntimePackageError as exc:
        print(f"BodyRig P3 Quest runtime package: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_RUNTIME_MATERIALIZED",
                "runtime_package_sha256": receipt["runtime_package_sha256"],
                "runtime_loader_contract": receipt["runtime_loader_contract"],
                "physical_device_review_required": True,
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
