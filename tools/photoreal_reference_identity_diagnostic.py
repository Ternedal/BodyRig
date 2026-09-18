from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _load_adapter(repo_root: Path):
    # Stage 7 is configured against the composite mesh adapter, even when the
    # bootstrap sources are flat. Load the exact same executable surface so the
    # request's composite revision remains comparable to the diagnostic.
    path = repo_root / "tools" / "photoreal_reference_vision_adapter_mesh.py"
    spec = importlib.util.spec_from_file_location("bodyrig_identity_diagnostic_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load reference adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diagnose why strict Photoreal V2 identity-bootstrap samples are accepted or rejected."
    )
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request_path = args.request.expanduser().resolve()
    model_root = args.model_root.expanduser().resolve()
    output = args.out.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"diagnostic output already exists: {output}")

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    adapter = _load_adapter(repo_root)
    request = _read_json(request_path, label="identity extractor request")

    if request.get("format") != adapter.IDENTITY_REQUEST or request.get("version") != 1:
        raise RuntimeError("request is not a Photoreal V2 identity extractor request")
    if request.get("measurement_only") is not True or request.get("train_only") is not True:
        raise RuntimeError("identity diagnostic requires the original measurement-only train request")
    if request.get("identity_matching_authority") is not False or request.get("teacher_training_authority") is not False:
        raise RuntimeError("identity request crossed its diagnostic authority boundary")
    if request.get("photoreal_acceptance_authority") is not False or request.get("production_activation") is not False:
        raise RuntimeError("identity request crossed photoreal/production authority")

    requested_revision = str(request.get("revision") or "").strip()
    current_revision = adapter._self_revision()
    if requested_revision != current_revision:
        raise RuntimeError(
            "identity request adapter revision does not match current adapter bytes; refuse non-comparable diagnostic"
        )
    observed_model_set = adapter.build_model_set(model_root)
    requested_model_set = str(request.get("model_set_sha256") or "").strip().lower()
    if observed_model_set.get("model_set_sha256") != requested_model_set:
        raise RuntimeError("identity request model-set SHA does not match current model root")

    manifest = adapter._load_model_manifest(model_root)
    runtime = adapter._load_runtime(manifest, device=args.device)

    rows: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    sources = request.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("identity request contains no sources")

    for source in sources:
        if not isinstance(source, dict):
            raise RuntimeError("identity request source is not an object")
        samples = source.get("reference_samples")
        if not isinstance(samples, list):
            raise RuntimeError("identity request source has no reference_samples")
        for sample in samples:
            if not isinstance(sample, dict):
                raise RuntimeError("identity reference sample is not an object")
            image, spatial = adapter._read_sample(runtime, source, sample)
            candidate_count = 0
            face_candidate_count = 0
            accepted = False
            reason = "unknown"
            if spatial:
                reason = "spatial-source-not-authoritative-for-bootstrap"
            else:
                candidates = adapter._candidates(runtime, image)
                candidate_count = len(candidates)
                face_candidate_count = sum(1 for candidate in candidates if candidate.get("face") is not None)
                if candidate_count == 0:
                    reason = "no-person-candidates"
                elif candidate_count > 1:
                    reason = "multiple-person-candidates"
                elif candidates[0].get("face") is None:
                    reason = "single-person-without-face"
                else:
                    vector = adapter._embedding(candidates[0]["face"], runtime.embedding_dimension)
                    if vector is None:
                        reason = "single-person-face-without-embedding"
                    else:
                        reason = "accepted"
                        accepted = True
            reasons[reason] += 1
            rows.append(
                {
                    "source_key": source.get("source_key"),
                    "timestamp_seconds": sample.get("timestamp_seconds"),
                    "eye": sample.get("eye"),
                    "candidate_count": candidate_count,
                    "face_candidate_count": face_candidate_count,
                    "accepted": accepted,
                    "reason": reason,
                }
            )

    result = {
        "format": "bodyrig-photoreal-identity-reference-diagnostic",
        "version": 1,
        "performer_id": request.get("performer_id"),
        "request_path": str(request_path),
        "adapter_revision": current_revision,
        "model_set_sha256": requested_model_set,
        "requested_device": args.device,
        "sample_count": len(rows),
        "accepted_count": sum(1 for row in rows if row["accepted"]),
        "rejected_count": sum(1 for row in rows if not row["accepted"]),
        "reason_counts": dict(sorted(reasons.items())),
        "samples": rows,
        "diagnostic_only": True,
        "identity_authority": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "format",
                    "sample_count",
                    "accepted_count",
                    "rejected_count",
                    "reason_counts",
                    "diagnostic_only",
                    "production_activation",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
