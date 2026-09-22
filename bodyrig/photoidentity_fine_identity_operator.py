from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .high_fidelity_continuation_status import (
    FINE_IDENTITY_GATE,
    continuation_paths,
    inspect_continuation,
)
from .high_fidelity_preview_jobs import HighFidelityPreviewError, manager as preview_manager
from .photoidentity_fine_identity_package import (
    PhotoIdentityFineIdentityPackageError,
    materialize_application,
)
from .photoidentity_fine_identity_reconstruction import (
    PhotoIdentityFineIdentityReconstructionError,
    run_reconstruction,
)
from .photoidentity_source_status import (
    PhotoIdentitySourceStatusError,
    inspect_source_status,
)

SHA40 = set("0123456789abcdef")


class PhotoIdentityFineIdentityOperatorError(RuntimeError):
    pass


def _git_state(root: Path) -> tuple[str, bool]:
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise PhotoIdentityFineIdentityOperatorError(
            "Git executable is unavailable for fine-identity operator validation"
        ) from exc
    revision = head.stdout.strip().lower()
    if (
        head.returncode != 0
        or len(revision) != 40
        or any(ch not in SHA40 for ch in revision)
    ):
        raise PhotoIdentityFineIdentityOperatorError(
            "could not resolve canonical BodyRig operator revision"
        )
    if dirty.returncode != 0:
        raise PhotoIdentityFineIdentityOperatorError(
            "could not inspect BodyRig operator checkout cleanliness"
        )
    return revision, not bool(dirty.stdout.strip())


def apply_terminal_fine_identity(
    *,
    preview_job_id: str,
    sweep_root: Path,
    adapter_config: Path,
    operator_root: Path,
) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    root = operator_root.expanduser().resolve()
    if root != repo_root:
        raise PhotoIdentityFineIdentityOperatorError(
            "operator root does not match the imported BodyRig checkout"
        )
    revision, clean = _git_state(root)
    if not clean:
        raise PhotoIdentityFineIdentityOperatorError(
            "BodyRig operator checkout is dirty; terminal fine-identity application is refused"
        )

    sweep = sweep_root.expanduser().resolve()
    config = adapter_config.expanduser().resolve()
    if not sweep.is_dir():
        raise PhotoIdentityFineIdentityOperatorError(
            f"PhotoIdentity sweep root is missing: {sweep}"
        )
    if not config.is_file() or config.is_symlink():
        raise PhotoIdentityFineIdentityOperatorError(
            f"pinned fine-identity adapter config is missing or symlinked: {config}"
        )

    try:
        preview = preview_manager.get(preview_job_id)
    except HighFidelityPreviewError as exc:
        raise PhotoIdentityFineIdentityOperatorError(str(exc)) from exc
    body_job_id = str(preview.get("body_job_id") or "").strip()
    if not body_job_id:
        raise PhotoIdentityFineIdentityOperatorError(
            "high-fidelity preview lacks originating body-job authority"
        )
    try:
        source_status = inspect_source_status(
            sweep,
            body_job_id=body_job_id,
        )
    except (OSError, ValueError, PhotoIdentitySourceStatusError) as exc:
        raise PhotoIdentityFineIdentityOperatorError(
            f"PhotoIdentity source authority no longer validates: {exc}"
        ) from exc
    if (
        source_status.get("stage") != "registered"
        or source_status.get("avatar_render_permitted") is not True
        or source_status.get("generic_guessing_permitted") is not False
        or source_status.get("production_activation") is not False
        or str(source_status.get("body_job_id") or "") != body_job_id
        or str(source_status.get("bodyrig_revision") or "").lower()
        != str(preview.get("bodyrig_revision") or "").lower()
    ):
        raise PhotoIdentityFineIdentityOperatorError(
            "PhotoIdentity sweep is not the exact registered source authority for this preview"
        )

    current = inspect_continuation(preview_job_id)
    if current.get("state") == "complete":
        gates = current.get("gates") or []
        if any(
            isinstance(gate, dict)
            and gate.get("id") == FINE_IDENTITY_GATE
            and gate.get("state") == "pass"
            for gate in gates
        ):
            return current
    next_gate = current.get("next_gate")
    if (
        not isinstance(next_gate, dict)
        or next_gate.get("gate") != FINE_IDENTITY_GATE
        or current.get("state") != "incomplete"
    ):
        raise PhotoIdentityFineIdentityOperatorError(
            "high-fidelity continuation is not waiting at the terminal fine-identity gate"
        )
    source_package_value = str(current.get("current_package_path") or "").strip()
    if not source_package_value:
        raise PhotoIdentityFineIdentityOperatorError(
            "terminal fine-identity gate lacks exact HFN source package"
        )
    source_package = Path(source_package_value).expanduser().resolve()
    if not source_package.is_file():
        raise PhotoIdentityFineIdentityOperatorError(
            "terminal fine-identity HFN source package is missing"
        )

    private_manifest = sweep / "private-fine-identity-review-manifest.json"
    attestation = sweep / "photoidentity-fine-identity-attestation.json"
    if not private_manifest.is_file() or private_manifest.is_symlink():
        raise PhotoIdentityFineIdentityOperatorError(
            "private fine-identity review manifest is missing or symlinked"
        )
    if not attestation.is_file() or attestation.is_symlink():
        raise PhotoIdentityFineIdentityOperatorError(
            "fine-identity attestation is missing or symlinked"
        )

    paths = continuation_paths(preview_job_id)
    application_root = paths["fine_identity"].expanduser().resolve()
    reconstruction_root = application_root / "reconstruction"
    package_root = application_root / "package"
    if application_root.exists():
        raise PhotoIdentityFineIdentityOperatorError(
            "terminal fine-identity application workspace already exists; status must validate or block it before retry"
        )

    try:
        run_reconstruction(
            source_package_path=source_package,
            private_manifest_path=private_manifest,
            attestation_path=attestation,
            config_path=config,
            output_dir=reconstruction_root,
            operator_bodyrig_revision=revision,
        )
        materialize_application(
            source_package_path=source_package,
            reconstruction_workspace=reconstruction_root,
            config_path=config,
            attestation_path=attestation,
            output_dir=package_root,
        )
        final = inspect_continuation(preview_job_id)
        expected_package = (package_root / "applied.mrbody").resolve()
        if (
            final.get("state") != "complete"
            or final.get("high_fidelity_complete") is not True
            or final.get("production_ready") is not False
            or final.get("production_activation") is not False
            or Path(str(final.get("current_package_path") or "")).expanduser().resolve()
            != expected_package
        ):
            raise PhotoIdentityFineIdentityOperatorError(
                "terminal application materialized but continuation did not revalidate it as complete"
            )
        return final
    except Exception:
        shutil.rmtree(application_root, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply terminal source-grounded PhotoIdentity fine identity to one exact HFN package."
    )
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--sweep-root", required=True, type=Path)
    parser.add_argument("--adapter-config", required=True, type=Path)
    parser.add_argument("--operator-root", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = apply_terminal_fine_identity(
            preview_job_id=args.preview_job_id,
            sweep_root=args.sweep_root,
            adapter_config=args.adapter_config,
            operator_root=args.operator_root,
        )
    except (
        OSError,
        ValueError,
        PhotoIdentityFineIdentityOperatorError,
        PhotoIdentityFineIdentityReconstructionError,
        PhotoIdentityFineIdentityPackageError,
    ) as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"BodyRig terminal fine-identity application: FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "BodyRig terminal fine-identity application: COMPLETE | "
            f"package={result.get('current_package_sha256')} | "
            "human_review_required=true | production=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
