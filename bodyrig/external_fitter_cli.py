from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .appearance_boundary import provenance_stage as appearance_boundary_stage
from .bodyprint_adjustment import (
    BodyprintAdjustmentEvidenceError,
    _write_create_only,
    adjustment_evidence_sha256,
    apply_adjustment_to_bodyprint,
    bind_request_to_proof,
    load_adjustment_evidence,
)
from .external_fitter import ExternalFitterError, run_external_fitter
from .identity import VisualIdentityError, bind_visual_identity_to_proof
from .package import MRBodyError, build_package
from .portable_identity import (
    PortableIdentityError,
    bind_portable_identity_to_evidence,
    load_portable_identity,
    provenance_identity_stage,
)
from .proof import ProofError, load_recovery_proof, read_canonical_json
from .subject_anatomy_provenance import (
    SubjectAnatomyProvenanceError,
    provenance_stage as subject_anatomy_provenance_stage,
)

CONFIG_FORMAT = "bodyrig-external-fitter-config"
CONFIG_VERSION = 1
ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
ADJUSTMENT_REQUEST_ENV = "BODYRIG_BODYPRINT_ADJUSTMENT_REQUEST"
BOUND_ADJUSTMENT_FILENAME = "bodyrig-bodyprint-adjustment.json"


class ExternalFitterConfigError(ValueError):
    pass


def validate_external_fitter_config(value: Any) -> dict[str, Any]:
    required = {
        "format",
        "version",
        "adapter",
        "revision",
        "command",
        "capabilities",
        "timeout_seconds",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ExternalFitterConfigError("external fitter config fields must match v1 exactly")
    if value["format"] != CONFIG_FORMAT or value["version"] != CONFIG_VERSION:
        raise ExternalFitterConfigError("unsupported external fitter config format/version")

    adapter = value["adapter"]
    if not isinstance(adapter, str) or not ADAPTER_RE.fullmatch(adapter):
        raise ExternalFitterConfigError("external fitter config adapter is invalid")
    revision = value["revision"]
    if not isinstance(revision, str) or not revision.strip() or len(revision) > 160:
        raise ExternalFitterConfigError("external fitter config revision is invalid")

    command = value["command"]
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 32
        or any(not isinstance(item, str) or not item or len(item) > 2000 for item in command)
    ):
        raise ExternalFitterConfigError("external fitter config command must be 1..32 non-empty argv strings")

    capabilities = value["capabilities"]
    capability_fields = {"visual_identity", "textures", "hair", "clothing"}
    if not isinstance(capabilities, dict) or set(capabilities) != capability_fields:
        raise ExternalFitterConfigError("external fitter capability fields must match v1 exactly")
    if any(type(capabilities[field]) is not bool for field in capability_fields):
        raise ExternalFitterConfigError("external fitter capabilities must be booleans")
    if capabilities["visual_identity"] is not True:
        raise ExternalFitterConfigError("external fitter must explicitly support visual_identity")
    if capabilities["clothing"] is not False:
        raise ExternalFitterConfigError(
            "external fitter clothing capability must be false; garments/outfits are external to the portable BodyRig body identity"
        )

    timeout = value["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86_400:
        raise ExternalFitterConfigError("external fitter timeout_seconds must be in 1..86400")
    return value


def _resolve_adjustment_path(args: argparse.Namespace) -> str:
    explicit = str(args.bodyprint_adjustment or "").strip()
    request_path = os.environ.get(ADJUSTMENT_REQUEST_ENV, "").strip()
    if explicit and request_path:
        raise BodyprintAdjustmentEvidenceError(
            f"pass --bodyprint-adjustment or {ADJUSTMENT_REQUEST_ENV}, never both"
        )
    if explicit:
        return explicit
    if not request_path:
        return ""

    request = read_canonical_json(request_path, label="BodyPrint adjustment request")
    evidence = bind_request_to_proof(request, proof_path=args.proof)
    evidence_path = Path(args.proof).expanduser().resolve().parent / BOUND_ADJUSTMENT_FILENAME
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
            avatar_vrm=fitted.fit.avatar_vrm,
            bodyprint=effective_bodyprint,
            provenance=provenance,
            thumbnail_png=fitted.fit.thumbnail_png,
        )
    except (
        OSError,
        ValueError,
        ProofError,
        VisualIdentityError,
        PortableIdentityError,
        BodyprintAdjustmentEvidenceError,
        SubjectAnatomyProvenanceError,
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
