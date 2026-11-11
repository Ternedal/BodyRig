"""Command line for POSE_READY (#1398 slice 1a). Runs in the ExAvatar runtime under WSL.

    python -m bodyrig.twin_pose_cli record-consent --workspace-root W --relation self --subject-is-adult --out C
    python -m bodyrig.twin_pose_cli pose --workspace-root W --consent C --smplx-model SMPLX_NEUTRAL.npz --out DIR
    python -m bodyrig.twin_pose_cli verify --out DIR

Exit codes: 0 written (or, for verify, verified); 2 not ready yet (the stage the motion needs
has not completed); 1 refused or failed, with the first failing check in "reason". The printed
summary names no subject, performer or source.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .twin_manifest import verify_twin_output
from .twin_pose import (
    RELATIONS,
    TwinPoseError,
    TwinPoseNotReady,
    export_pose,
    load_template_rest_joints,
    record_consent,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bodyrig.twin_pose_cli", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    consent = commands.add_parser("record-consent", help="record, once, who the subject is for one workspace")
    consent.add_argument("--workspace-root", required=True)
    consent.add_argument("--relation", required=True, choices=RELATIONS,
                         help="self: the operator is the subject; consenting-adult: an adult who consented")
    consent.add_argument("--subject-is-adult", action="store_true",
                         help="required: states that the subject is an adult")
    consent.add_argument("--consent-evidence-sha256", default=None,
                         help="SHA-256 of the consent document you keep (required for consenting-adult)")
    consent.add_argument("--out", required=True, help="where to write the record; never overwritten")

    pose = commands.add_parser("pose", help="write motion.bvh, motion.json and the manifest")
    pose.add_argument("--workspace-root", required=True)
    pose.add_argument("--consent", required=True, help="the record written by record-consent")
    pose.add_argument("--smplx-model", required=True, help="SMPLX_NEUTRAL.npz, for the zero-shape rest skeleton")
    pose.add_argument("--out", required=True, help="private output directory")
    pose.add_argument("--source", choices=("auto", "init", "smoothed"), default="auto",
                      help="auto: smoothed when smplx-smooth is done, else the Hand4Whole init")

    verify = commands.add_parser("verify", help="check a POSE_READY output against its manifest (read-only)")
    verify.add_argument("--out", required=True, help="the directory pose wrote")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "record-consent":
            if not args.subject_is_adult:
                raise TwinPoseError("--subject-is-adult is required: only an adult subject can be recorded")
            document = record_consent(workspace_root=args.workspace_root, out_path=args.out, relation=args.relation,
                                      subject_is_adult=True, consent_evidence_sha256=args.consent_evidence_sha256)
            print(json.dumps({"ok": True, "consent_sha256": document["consent_sha256"],
                              "subject_relation": document["subject_relation"]}, sort_keys=True))
            return 0
        if args.command == "verify":
            try:
                result = verify_twin_output(args.out)
            except TwinPoseError as exc:
                print(json.dumps({"ok": False, "verified": False, "reason": str(exc)}, sort_keys=True))
                return 1
            print(json.dumps({"ok": True, "verified": True, "source": result.source,
                              "valid_samples": result.valid_samples, "samples": result.samples,
                              "manifest_sha256": result.manifest_sha256}, sort_keys=True))
            return 0
        rest, model_sha = load_template_rest_joints(args.smplx_model)
        manifest = export_pose(workspace_root=args.workspace_root, consent_path=args.consent, out_dir=args.out,
                               rest_joints=rest, template_model_sha256=model_sha, source=args.source)
    except TwinPoseNotReady as exc:
        print(json.dumps({"ok": False, "ready": False, "reason": str(exc)}, sort_keys=True))
        return 2
    except TwinPoseError as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps({
        "ok": True,
        "state": manifest["state"],
        "source": manifest["motion_source"]["source"],
        "valid_samples": manifest["timing"]["valid_samples"],
        "samples": manifest["timing"]["samples"],
        "manifest_sha256": manifest["manifest_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
