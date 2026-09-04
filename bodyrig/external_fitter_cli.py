from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .appearance_boundary import appearance_boundary_stage
from .bodyprint_adjustment import (
    BodyprintAdjustmentEvidenceError,
    adjustment_evidence_sha256,
    apply_adjustment_to_bodyprint,
    load_adjustment_evidence,
)
from .external_fitter import (
    ExternalFitterConfigError,
    ExternalFitterError,
    run_external_fitter,
    validate_external_fitter_config,
)
from .package import MRBodyError, build_package
from .portable_identity import (
    PortableIdentityError,
    bind_portable_identity_to_evidence,
    load_portable_identity,
    provenance_identity_stage,
)
from .proof import ProofError, load_recovery_proof, read_canonical_json
from .retained_anatomy_source import (
    RetainedAnatomySourceError,
    publish_retained_anatomy_source,
)
from .sith_body_geometry_authority import (
    SithBodyGeometryAuthorityError,
    bind_sith_body_geometry_authority,
)
from .subject_anatomy_provenance import (
    SubjectAnatomyProvenanceError,
    subject_anatomy_provenance_stage,
)
from .visual_identity import VisualIdentityError, bind_visual_identity_to_proof

BUILTIN_SITH_ADAPTER = "sith-smplx-vrm"
RETAINED_ANATOMY_DIRNAME = "retained-anatomy-source"


def _write_create_only(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"evidence path already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _resolve_adjustment_path(args: argparse.Namespace) -> str:
    value = str(args.bodyprint_adjustment or "").strip()
    return value


def _bodyprint_evidence_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".bodyprint-adjustment.json")


def _persist_adjustment_evidence(output: Path, evidence: dict) -> str:
    evidence_path = _bodyprint_evidence_path(output)
    _write_create_only(evidence_path, evidence)
    return str(evidence_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an isolated high-fidelity avatar fitter and build a validated .mrbody package."
    )
    parser.add_argument("proof", help="bodyrig-recovery-proof.json")
    parser.add_argument("--identity-profile", required=True, help="bodyrig-visual-identity v1 JSON")
    parser.add_argument(
        "--identity-workspace",
        required=True,
        help="Private local workspace containing source-derived material for the external fitter",
    )
    parser.add_argument("--config", required=True, help="Local bodyrig-external-fitter-config v1 JSON")
    parser.add_argument("--body-id", required=True, help="Operator-facing BodyRig alias")
    parser.add_argument(
        "--portable-identity",
        default="",
        help="Optional bodyrig-portable-identity v1 receipt; when present it is the canonical package identity authority",
    )
    parser.add_argument(
        "--bodyprint-adjustment",
        default="",
        help="Optional proof-bound bodyrig-bodyprint-adjustment-evidence v1 JSON",
    )
    parser.add_argument(
        "--subject-anatomy-refit",
        default="",
        help="Optional comparison-only bodyrig-subject-anatomy-refit v1 evidence to bind into package provenance",
    )
    parser.add_argument("--name", required=True, help="Display name for the avatar")
    parser.add_argument("--out", required=True, help="Output .mrbody path")
    args = parser.parse_args(argv)

    try:
        proof = load_recovery_proof(args.proof)
        identity = bind_visual_identity_to_proof(
            read_canonical_json(args.identity_profile, label="visual identity profile"),
            proof,
        )
        config = validate_external_fitter_config(
            read_canonical_json(args.config, label="external fitter config")
        )
        portable_identity = None
        package_body_id = args.body_id
        if args.portable_identity:
            portable_identity = bind_portable_identity_to_evidence(
                load_portable_identity(args.portable_identity),
                proof=proof,
                visual_identity=identity,
                requested_alias=args.body_id,
            )
            package_body_id = portable_identity["body_id"]

        adjustment_evidence = None
        adjustment_request = None
        effective_bodyprint = proof["bodyprint"]
        adjustment_hash = None
        adjustment_path = _resolve_adjustment_path(args)
        if adjustment_path:
            adjustment_evidence = load_adjustment_evidence(
                adjustment_path,
                proof_path=args.proof,
            )
            adjustment_request = adjustment_evidence["adjustment"]
            effective_bodyprint = apply_adjustment_to_bodyprint(
                proof["bodyprint"],
                adjustment_evidence,
            )
            adjustment_hash = adjustment_evidence_sha256(adjustment_path)

        anatomy_stage = None
        if str(args.subject_anatomy_refit or "").strip():
            anatomy_stage = subject_anatomy_provenance_stage(args.subject_anatomy_refit)

        fitted = run_external_fitter(
            config["command"],
            workspace=args.identity_workspace,
            bodyprint=effective_bodyprint,
            bodyprint_adjustment=adjustment_request,
            name=args.name,
            identity=identity,
            adapter=config["adapter"],
            revision=config["revision"],
            timeout_seconds=config["timeout_seconds"],
        )
        avatar_vrm = fitted.fit.avatar_vrm
        if config["adapter"] == BUILTIN_SITH_ADAPTER:
            avatar_vrm = bind_sith_body_geometry_authority(
                avatar_vrm,
                args.identity_workspace,
                bodyprint_adjustment=adjustment_request,
                bodyprint_adjustment_evidence_sha256=adjustment_hash,
            )

        pipeline = [
            {
                "stage": "body-recovery",
                "adapter": proof["adapter"],
                "revision": proof["revision"],
            },
        ]
        if adjustment_hash is not None:
            pipeline.append(
                {
                    "stage": "bodyprint-adjustment",
                    "adapter": "bodyrig.bodyprint_adjustment",
                    "revision": adjustment_hash,
                }
            )
        if anatomy_stage is not None:
            pipeline.append(anatomy_stage)
        pipeline.append(
            {
                "stage": "visual-identity-capture",
                "adapter": identity["adapter"],
                "revision": identity["revision"],
            }
        )
        if portable_identity is not None:
            pipeline.append(provenance_identity_stage(portable_identity))
        pipeline.append(appearance_boundary_stage())
        pipeline.append(
            {
                "stage": "avatar-fitting",
                "adapter": fitted.fit.adapter,
                "revision": fitted.fit.revision,
            }
        )
        provenance = {
            "format": "modelrig-body-provenance",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": {"kind": "user-supplied-local-media", "count": proof["source_count"]},
            "synthetic_avatar": True,
            "pipeline": pipeline,
        }
        output = Path(args.out).expanduser().resolve()
        build_package(
            output,
            body_id=package_body_id,
            name=args.name,
            avatar_vrm=avatar_vrm,
            bodyprint=effective_bodyprint,
            provenance=provenance,
            thumbnail_png=fitted.fit.thumbnail_png,
        )
        if config["adapter"] == BUILTIN_SITH_ADAPTER:
            publish_retained_anatomy_source(
                args.identity_workspace,
                output.parent / RETAINED_ANATOMY_DIRNAME,
            )
    except (
        OSError,
        ValueError,
        ProofError,
        VisualIdentityError,
        PortableIdentityError,
        BodyprintAdjustmentEvidenceError,
        SubjectAnatomyProvenanceError,
        RetainedAnatomySourceError,
        SithBodyGeometryAuthorityError,
        ExternalFitterConfigError,
        ExternalFitterError,
        MRBodyError,
    ) as exc:
        print(f"BodyRig external avatar fitting: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
