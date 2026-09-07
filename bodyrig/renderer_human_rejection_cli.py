from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .acceptance_status import (
    AcceptanceStatusError,
    GateAInfo,
    PlatformPaths,
    _platform_paths,
    _sha256,
    _validate_deformation,
    _validate_gate_a,
    _validate_probe,
)
from .renderer_human_rejection import (
    FAILED_CHECKS,
    RendererHumanRejectionError,
    read_rejection,
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


def _binding(acceptance_dir: Path, platform: str) -> tuple[GateAInfo, PlatformPaths]:
    gate = _validate_gate_a(acceptance_dir / "bodyrig-acceptance.json")
    if platform == "windows-unity-univrm":
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
    probe = _validate_probe(paths.probe, platform=platform, gate=gate)
    _validate_deformation(paths.deformation, platform=platform, probe=probe, gate=gate)
    return gate, paths


def _expected(gate: GateAInfo, paths: PlatformPaths) -> dict[str, Any]:
    return {
        "bodyrig_revision": gate.revision,
        "body_id": gate.body_id,
        "automated_report_sha256": _sha256(gate.path),
        "probe_report_sha256": _sha256(paths.probe),
        "deformation_report_sha256": _sha256(paths.deformation),
        "package_sha256": gate.package_hash,
        "runtime_manifest_sha256": gate.runtime_hash,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    acceptance_dir = args.acceptance_dir.expanduser().resolve()
    receipt_path: Path | None = None
    try:
        gate, paths = _binding(acceptance_dir, args.platform)
        receipt = write_rejection(
            acceptance_dir,
            platform=args.platform,
            **_expected(gate, paths),
            failed_checks=args.failed_check,
            quality_note=args.quality_note,
        )
        receipt_path = Path(str(receipt["rejection_path"])).resolve()
        try:
            current_gate, current_paths = _binding(acceptance_dir, args.platform)
            read_rejection(
                acceptance_dir,
                platform=args.platform,
                **_expected(current_gate, current_paths),
            )
        except (AcceptanceStatusError, RendererHumanRejectionError, OSError, ValueError) as exc:
            try:
                receipt_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                raise RendererHumanRejectionError(
                    f"renderer evidence changed after rejection write and non-authoritative receipt cleanup failed: {cleanup_exc}"
                ) from exc
            raise RendererHumanRejectionError(
                "renderer evidence authority changed after rejection write; removed non-authoritative rejection receipt"
            ) from exc
    except (AcceptanceStatusError, RendererHumanRejectionError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, **receipt}, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
