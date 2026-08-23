from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .external_fitter import ExternalFitterError, run_external_fitter
from .identity import VisualIdentityError, bind_visual_identity_to_proof
from .package import MRBodyError, build_package
from .proof import ProofError, load_recovery_proof, read_canonical_json

CONFIG_FORMAT = "bodyrig-external-fitter-config"
CONFIG_VERSION = 1
ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


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

    timeout = value["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86_400:
        raise ExternalFitterConfigError("external fitter timeout_seconds must be in 1..86400")
    return value


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
    parser.add_argument("--body-id", required=True, help="Path-safe BodyRig id")
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
        fitted = run_external_fitter(
            config["command"],
            workspace=args.identity_workspace,
            bodyprint=proof["bodyprint"],
            name=args.name,
            identity=identity,
            adapter=config["adapter"],
            revision=config["revision"],
            timeout_seconds=config["timeout_seconds"],
        )

        provenance = {
            "format": "modelrig-body-provenance",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": {"kind": "user-supplied-local-media", "count": proof["source_count"]},
            "synthetic_avatar": True,
            "pipeline": [
                {
                    "stage": "body-recovery",
                    "adapter": proof["adapter"],
                    "revision": proof["revision"],
                },
                {
                    "stage": "visual-identity-capture",
                    "adapter": identity["adapter"],
                    "revision": identity["revision"],
                },
                {
                    "stage": "avatar-fitting",
                    "adapter": fitted.fit.adapter,
                    "revision": fitted.fit.revision,
                },
            ],
        }
        output = Path(args.out).expanduser().resolve()
        build_package(
            output,
            body_id=args.body_id,
            name=args.name,
            avatar_vrm=fitted.fit.avatar_vrm,
            bodyprint=proof["bodyprint"],
            provenance=provenance,
            thumbnail_png=fitted.fit.thumbnail_png,
        )
    except (
        OSError,
        ValueError,
        ProofError,
        VisualIdentityError,
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
