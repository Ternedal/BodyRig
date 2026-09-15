from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

WORKSPACE_FORMAT = "bodyrig-photoreal-exavatar-workspace"
RECEIPT_FORMAT = "bodyrig-photoreal-exavatar-hand4whole-assets"
VERSION = 1

# The pinned Hand4Whole demo imports utils.human_models, which instantiates
# SMPLX() and SMPL() at import time. Keep the wider documented MANO/FLAME tree
# present too because the vendored human-model utilities refer to it and later
# code must not depend on a partial, accidental import path.
REQUIRED_RELATIVE_FILES: tuple[str, ...] = (
    "smpl/SMPL_NEUTRAL.pkl",
    "smplx/SMPLX_NEUTRAL.npz",
    "smplx/SMPLX_MALE.npz",
    "smplx/SMPLX_FEMALE.npz",
    "smplx/SMPLX_to_J14.pkl",
    "smplx/MANO_SMPLX_vertex_ids.pkl",
    "smplx/SMPL-X__FLAME_vertex_ids.npy",
    "mano/MANO_LEFT.pkl",
    "mano/MANO_RIGHT.pkl",
    "flame/FLAME_NEUTRAL.pkl",
    "flame/FLAME_MALE.pkl",
    "flame/FLAME_FEMALE.pkl",
    "flame/flame_dynamic_embedding.npy",
    "flame/flame_static_embedding.pkl",
)


class PhotorealExAvatarHand4WholeStageError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealExAvatarHand4WholeStageError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_workspace(root: Path) -> dict[str, Any]:
    path = root / "workspace-receipt.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarHand4WholeStageError(f"workspace receipt is unreadable: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != WORKSPACE_FORMAT or value.get("version") != VERSION:
        raise PhotorealExAvatarHand4WholeStageError("workspace receipt format/version mismatch")
    if value.get("held_out_evaluation_disclosed") is not False or value.get("original_video_copied") is not False:
        raise PhotorealExAvatarHand4WholeStageError("workspace disclosed forbidden source/eval data")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealExAvatarHand4WholeStageError("workspace crossed downstream authority")
    declared = _sha(value.get("workspace_sha256"), label="workspace SHA-256")
    if _digest(value, omit="workspace_sha256") != declared:
        raise PhotorealExAvatarHand4WholeStageError("workspace receipt digest mismatch")
    return value


def stage_hand4whole_assets(*, workspace_root: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealExAvatarHand4WholeStageError(f"ExAvatar workspace not found: {root}")
    workspace = _load_workspace(root)

    source = root / "repos" / "ExAvatar_RELEASE" / "fitting" / "common" / "utils" / "human_model_files"
    target = root / "repos" / "Hand4Whole_RELEASE" / "common" / "utils" / "human_model_files"
    receipt_path = root / "hand4whole-assets-receipt.json"
    if receipt_path.exists():
        raise PhotorealExAvatarHand4WholeStageError(f"Hand4Whole asset receipt already exists: {receipt_path}")
    if not source.is_dir():
        raise PhotorealExAvatarHand4WholeStageError("workspace ExAvatar human-model tree is missing")
    if target.exists() or target.is_symlink():
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole human-model destination already exists")

    records: list[dict[str, Any]] = []
    for relative in REQUIRED_RELATIVE_FILES:
        path = source / relative
        if not path.is_file() or path.stat().st_size < 1:
            raise PhotorealExAvatarHand4WholeStageError(f"required Hand4Whole human-model asset missing: {relative}")
        records.append(
            {
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _file_sha(path),
            }
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source, target_is_directory=True)
    if not target.is_symlink() or target.resolve() != source:
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole human-model symlink did not resolve to workspace source tree")
    for record in records:
        staged = target / record["relative_path"]
        if not staged.is_file() or _file_sha(staged) != record["sha256"]:
            raise PhotorealExAvatarHand4WholeStageError(f"Hand4Whole staged asset verification failed: {record['relative_path']}")

    result: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": VERSION,
        "workspace_sha256": workspace["workspace_sha256"],
        "smplx_gender": workspace["smplx_gender"],
        "source_tree_relative_path": source.relative_to(root).as_posix(),
        "target_tree_relative_path": target.relative_to(root).as_posix(),
        "target_is_symlink": True,
        "required_asset_count": len(records),
        "assets": records,
        "held_out_evaluation_disclosed": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "production_activation": False,
    }
    result["hand4whole_assets_sha256"] = _digest(result, omit="hand4whole_assets_sha256")
    receipt_path.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def validate_hand4whole_assets_receipt(*, workspace_root: str | Path) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve()
    workspace = _load_workspace(root)
    path = root / "hand4whole-assets-receipt.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarHand4WholeStageError(f"Hand4Whole asset receipt is unreadable: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != RECEIPT_FORMAT or value.get("version") != VERSION:
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset receipt format/version mismatch")
    if value.get("workspace_sha256") != workspace["workspace_sha256"]:
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset receipt belongs to different workspace")
    declared = _sha(value.get("hand4whole_assets_sha256"), label="Hand4Whole asset receipt SHA-256")
    if _digest(value, omit="hand4whole_assets_sha256") != declared:
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset receipt digest mismatch")
    if value.get("target_is_symlink") is not True or value.get("required_asset_count") != len(REQUIRED_RELATIVE_FILES):
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole staged asset policy mismatch")
    if value.get("held_out_evaluation_disclosed") is not False or value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset stage crossed authority boundary")
    if value.get("production_activation") is not False:
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset stage crossed production authority")

    target = root / str(value.get("target_tree_relative_path") or "")
    if not target.is_symlink():
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole staged human-model tree is no longer a symlink")
    records = value.get("assets")
    if not isinstance(records, list) or len(records) != len(REQUIRED_RELATIVE_FILES):
        raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset receipt inventory is invalid")
    seen: set[str] = set()
    for raw in records:
        if not isinstance(raw, Mapping):
            raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset receipt entry is invalid")
        relative = str(raw.get("relative_path") or "")
        if relative not in REQUIRED_RELATIVE_FILES or relative in seen:
            raise PhotorealExAvatarHand4WholeStageError("Hand4Whole asset receipt path inventory is invalid")
        seen.add(relative)
        staged = target / relative
        if not staged.is_file() or staged.stat().st_size != raw.get("size_bytes"):
            raise PhotorealExAvatarHand4WholeStageError(f"Hand4Whole staged asset size mismatch: {relative}")
        if _file_sha(staged) != _sha(raw.get("sha256"), label=f"Hand4Whole staged asset SHA-256 {relative}"):
            raise PhotorealExAvatarHand4WholeStageError(f"Hand4Whole staged asset SHA mismatch: {relative}")
    return value
