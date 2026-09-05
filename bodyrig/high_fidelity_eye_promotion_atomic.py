from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import high_fidelity_eye_promotion as core


HighFidelityEyePromotionError = core.HighFidelityEyePromotionError
read_promotion = core.read_promotion


def _final_root_for_request(
    preview_job_id: str,
    *,
    candidate_package_path: str | Path,
    target_package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    eye_runtime_dir: str | Path,
    bridge_script_sha256: str,
) -> Path:
    _rebuild, _eye_vrm, rebuild_receipt_path, rebuild_receipt_sha = core._validated_rebuild(
        preview_job_id,
        candidate_package_path=candidate_package_path,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
        eye_runtime_dir=eye_runtime_dir,
        bridge_script_sha256=bridge_script_sha256,
    )
    if not rebuild_receipt_path.is_file():
        raise HighFidelityEyePromotionError("eye-only rebuild receipt disappeared before atomic promotion")
    target = Path(target_package_path).expanduser().resolve()
    if not target.is_file():
        raise HighFidelityEyePromotionError(f"promotion destination source package is missing: {target}")
    target_sha = core._sha256_file(target)
    return core._promotion_root(preview_job_id, target_sha=target_sha, rebuild_sha=rebuild_receipt_sha)


def write_promotion(
    preview_job_id: str,
    *,
    candidate_package_path: str | Path,
    target_package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    eye_runtime_dir: str | Path,
    bridge_script_sha256: str,
    promotion_bodyrig_revision: str,
) -> dict[str, Any]:
    """Canonical eye-promotion entrypoint with final-directory rollback.

    The lower-level materializer already cleans its partial staging directory. This
    guard closes the remaining rename/revalidation window: if the lower-level
    write moves staging to the final authority directory and then raises while
    revalidating those bytes, only the final directory created by this invocation
    is removed. A pre-existing create-only authority is never removed.
    """

    common = dict(
        candidate_package_path=candidate_package_path,
        target_package_path=target_package_path,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
        eye_runtime_dir=eye_runtime_dir,
        bridge_script_sha256=bridge_script_sha256,
    )
    final_root = _final_root_for_request(preview_job_id, **common)
    existed_before = final_root.exists()
    try:
        return core.write_promotion(
            preview_job_id,
            promotion_bodyrig_revision=promotion_bodyrig_revision,
            **common,
        )
    except Exception:
        if not existed_before and final_root.exists():
            shutil.rmtree(final_root, ignore_errors=True)
        raise
