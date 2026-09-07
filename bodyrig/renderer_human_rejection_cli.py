from __future__ import annotations

import argparse
import json
from pathlib import Path

from .acceptance_status import (
    AcceptanceStatusError,
    _platform_paths,
    _sha256,
    _validate_deformation,
    _validate_gate_a,
    _validate_probe,
)
from .renderer_human_rejection import (
    FAILED_CHECKS,
    RendererHumanRejectionError,
    write_rejection,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persist a create-only BodyRig renderer human rejection bound to exact physical evidence."
    )
    parser.add_argument("--acceptance-dir", type=Path, required=True)
    parser.add_argument(
        "--platform",
        required=True,
        choices=("windows-unity-univrm", "android-quest-class"),
    )
    parser.add_argument("--failed-check", action="append", required=True, choices=sorted(FAILED_CHECKS))
    parser.add_argument("--quality-note", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    acceptance_dir = args.acceptance_dir.expanduser().resolve()
    try:
        gate = _validate_gate_a(acceptance_dir / "bodyrig-acceptance.json")
        if args.platform == "windows-unity-univrm":
            prefix = "windows"
            attestation_name = "bodyrig-renderer-acceptance-windows.json"
        else:
            prefix = "quest"
            attestation_name = "bodyrig-renderer-acceptance-quest.json"
        paths = _platform_paths(acceptance_dir, prefix, attestation_name)
        if not paths.probe.is_file() or not paths.deformation.is_file():
            raise RendererHumanRejectionError(
                f"{prefix} renderer rejection requires the complete canonical machine/deformation evidence pair"
            )
        probe = _validate_probe(paths.probe, platform=args.platform, gate=gate)
        _validate_deformation(paths.deformation, platform=args.platform, probe=probe, gate=gate)
        receipt = write_rejection(
            acceptance_dir,
            platform=args.platform,
            bodyrig_revision=gate.revision,
            body_id=gate.body_id,
            automated_report_sha256=_sha256(gate.path),
            probe_report_sha256=_sha256(paths.probe),
            deformation_report_sha256=_sha256(paths.deformation),
            package_sha256=gate.package_hash,
            runtime_manifest_sha256=gate.runtime_hash,
            failed_checks=args.failed_check,
            quality_note=args.quality_note,
        )
    except (AcceptanceStatusError, RendererHumanRejectionError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **receipt}, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
