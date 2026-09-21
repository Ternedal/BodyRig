from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_authority import (
    resume_external_teacher_files_strict,
    run_external_teacher_files_strict,
    validate_external_teacher_files_strict,
)
from .photoreal_teacher_runner import PhotorealTeacherRunnerError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one pinned external Photoreal V2 teacher benchmark without disclosing held-out bytes."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--teacher-input", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace = args.workspace.expanduser().resolve()
        if args.reuse_existing and workspace.is_dir():
            manifest = workspace / "output" / "teacher-manifest.json"
            if manifest.is_file():
                result = validate_external_teacher_files_strict(
                    args.config,
                    args.teacher_input,
                    workspace,
                )
            else:
                result = resume_external_teacher_files_strict(
                    args.config,
                    args.teacher_input,
                    workspace,
                )
        else:
            result = run_external_teacher_files_strict(
                args.config,
                args.teacher_input,
                workspace,
            )
    except PhotorealTeacherRunnerError as exc:
        print(f"BodyRig photoreal teacher: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "selected_epoch_id": result["selected_epoch_id"],
                "adapter": result["adapter"],
                "adapter_revision": result["adapter_revision"],
                "upstream_repository": result["upstream_repository"],
                "upstream_commit": result["upstream_commit"],
                "training_complete": result["training_complete"],
                "artifact_count": len(result["artifacts"]),
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "human_visual_acceptance_required": result["human_visual_acceptance_required"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
