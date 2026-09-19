from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


BANK_FORMAT = "bodyrig-photoreal-identity-bank"
BANK_VERSION = 1
REFERENCE_SET_FORMAT = "bodyrig-fidelity-reference-set"
REFERENCE_SET_VERSION = 1


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _load_adapter(repo_root: Path):
    path = repo_root / "tools" / "photoreal_reference_vision_adapter_mesh.py"
    spec = importlib.util.spec_from_file_location(
        "bodyrig_portrait_seed_diagnostic_adapter",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load reference adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise RuntimeError(f"{label} is invalid")
    return text


def _embedding(value: Any, *, dimension: int) -> list[float]:
    if not isinstance(value, list) or len(value) != dimension:
        raise RuntimeError("identity bank embedding dimension mismatch")
    result = [float(item) for item in value]
    if any(not math.isfinite(item) for item in result):
        raise RuntimeError("identity bank embedding contains non-finite value")
    norm = math.sqrt(sum(item * item for item in result))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise RuntimeError("identity bank embedding has invalid norm")
    return [item / norm for item in result]


def _normalized_mean(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise RuntimeError("cannot build centroid from no vectors")
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise RuntimeError("embedding dimensions are inconsistent")
    mean = [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(dimension)
    ]
    norm = math.sqrt(sum(value * value for value in mean))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise RuntimeError("embedding centroid collapsed")
    return [value / norm for value in mean]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise RuntimeError("embedding dimensions are inconsistent")
    return max(
        -1.0,
        min(
            1.0,
            sum(a * b for a, b in zip(left, right, strict=True)),
        ),
    )


def _summary(values: Iterable[float]) -> dict[str, float] | None:
    numbers = [float(value) for value in values]
    if not numbers:
        return None
    return {
        "min": round(min(numbers), 9),
        "median": round(statistics.median(numbers), 9),
        "max": round(max(numbers), 9),
    }


def _validate_bank(
    bank: Mapping[str, Any],
    *,
    adapter_revision: str,
    observed_model_set_sha256: str,
) -> tuple[str, int, list[Mapping[str, Any]]]:
    if bank.get("format") != BANK_FORMAT or bank.get("version") != BANK_VERSION:
        raise RuntimeError("identity bank format/version mismatch")
    performer_id = str(bank.get("performer_id") or "").strip()
    if not performer_id:
        raise RuntimeError("identity bank performer id is missing")
    if str(bank.get("extractor_revision") or "").strip() != adapter_revision:
        raise RuntimeError(
            "identity bank extractor revision does not match current reference adapter bytes"
        )
    if _sha(
        bank.get("model_set_sha256"),
        label="identity bank model-set SHA-256",
    ) != observed_model_set_sha256:
        raise RuntimeError("identity bank model set does not match current model root")
    if bank.get("build_only") is not True or bank.get("production_activation") is not False:
        raise RuntimeError("identity bank crossed its build/production boundary")
    dimension = bank.get("embedding_dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 32 <= dimension <= 4096:
        raise RuntimeError("identity bank embedding dimension is invalid")
    references = bank.get("references")
    if not isinstance(references, list) or not references:
        raise RuntimeError("identity bank contains no references")
    return performer_id, dimension, references


def _validate_reference_set(
    manifest: Mapping[str, Any],
    *,
    performer_id: str,
) -> list[Mapping[str, Any]]:
    if (
        manifest.get("format") != REFERENCE_SET_FORMAT
        or manifest.get("version") != REFERENCE_SET_VERSION
    ):
        raise RuntimeError("Stash reference-set format/version mismatch")
    performer = manifest.get("performer")
    if not isinstance(performer, Mapping):
        raise RuntimeError("Stash reference-set performer is missing")
    if str(performer.get("id") or "").strip() != performer_id:
        raise RuntimeError("Stash reference-set performer does not match identity bank")
    privacy = manifest.get("privacy")
    if not isinstance(privacy, Mapping) or privacy.get("private_workspace_only") is not True:
        raise RuntimeError("Stash reference set is not marked private-workspace-only")
    if manifest.get("semantics") != "visual-fidelity-not-identity-verification":
        raise RuntimeError("unexpected Stash reference-set semantics")
    references = manifest.get("references")
    if not isinstance(references, list) or not references:
        raise RuntimeError("Stash reference set contains no references")
    return [item for item in references if isinstance(item, Mapping)]


def _seed_measurements(
    *,
    adapter: Any,
    runtime: Any,
    reference_root: Path,
    manifest_references: list[Mapping[str, Any]],
    dimension: int,
) -> tuple[list[dict[str, Any]], list[list[float]]]:
    rows: list[dict[str, Any]] = []
    vectors: list[list[float]] = []
    for item in manifest_references:
        if item.get("exclusive_subject") is not True:
            continue
        filename = str(item.get("file") or "").strip()
        if not filename:
            raise RuntimeError("exclusive Stash reference lacks local file")
        path = (reference_root / filename).resolve()
        try:
            path.relative_to(reference_root)
        except ValueError as exc:
            raise RuntimeError("Stash reference path escapes reference root") from exc
        raw = path.read_bytes()
        expected_sha = _sha(item.get("sha256"), label="Stash reference SHA-256")
        if _sha256_bytes(raw) != expected_sha:
            raise RuntimeError(f"Stash reference bytes changed: {filename}")
        image = runtime.cv2.imread(str(path), runtime.cv2.IMREAD_COLOR)
        if image is None or getattr(image, "size", 0) == 0:
            rows.append(
                {
                    "kind": item.get("kind"),
                    "stash_id": item.get("stash_id"),
                    "file": filename,
                    "accepted": False,
                    "reason": "decode-failed",
                }
            )
            continue
        candidates = adapter.base._candidates(runtime, image)
        face_candidates = [
            candidate
            for candidate in candidates
            if candidate.get("face") is not None
        ]
        if len(candidates) != 1 or len(face_candidates) != 1:
            rows.append(
                {
                    "kind": item.get("kind"),
                    "stash_id": item.get("stash_id"),
                    "file": filename,
                    "accepted": False,
                    "reason": (
                        "no-single-face"
                        if not face_candidates
                        else "ambiguous-multiple-candidates"
                    ),
                    "candidate_count": len(candidates),
                    "face_candidate_count": len(face_candidates),
                }
            )
            continue
        face = face_candidates[0]["face"]
        vector = adapter.base._embedding(face, dimension)
        if vector is None:
            rows.append(
                {
                    "kind": item.get("kind"),
                    "stash_id": item.get("stash_id"),
                    "file": filename,
                    "accepted": False,
                    "reason": "embedding-unavailable",
                }
            )
            continue
        height, width = image.shape[:2]
        vectors.append(vector)
        rows.append(
            {
                "kind": item.get("kind"),
                "stash_id": item.get("stash_id"),
                "file": filename,
                "accepted": True,
                "reason": "accepted",
                "candidate_count": len(candidates),
                "face_candidate_count": len(face_candidates),
                "face_visibility": adapter.base._face_visibility(
                    face,
                    width=width,
                    height=height,
                ),
                "view_bin": adapter.base._view_bin(face),
                "sharpness": adapter.base._sharpness(runtime, image),
                "frame_sha256": adapter.base._frame_sha(image),
            }
        )
    return rows, vectors


def _group_diagnostics(
    references: list[Mapping[str, Any]],
    *,
    dimension: int,
    all_seed_centroid: list[float],
    profile_centroid: list[float] | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in references:
        if not isinstance(item, Mapping):
            raise RuntimeError("identity bank contains invalid reference")
        group_id = str(item.get("group_id") or "").strip()
        if not group_id:
            raise RuntimeError("identity bank reference lacks group id")
        grouped[group_id].append(item)

    rows: list[dict[str, Any]] = []
    for group_id, items in grouped.items():
        vectors = [
            _embedding(item.get("embedding"), dimension=dimension)
            for item in items
        ]
        centroid = _normalized_mean(vectors)
        all_scores = [_cosine(vector, all_seed_centroid) for vector in vectors]
        row: dict[str, Any] = {
            "group_id": group_id,
            "reference_count": len(vectors),
            "source_keys": sorted(
                {
                    str(item.get("source_key") or "")
                    for item in items
                    if str(item.get("source_key") or "").strip()
                }
            ),
            "exclusive_seed_centroid_cosine": round(
                _cosine(centroid, all_seed_centroid),
                9,
            ),
            "exclusive_seed_reference_cosine":
                _summary(all_scores),
        }
        if profile_centroid is not None:
            profile_scores = [
                _cosine(vector, profile_centroid)
                for vector in vectors
            ]
            row["profile_seed_centroid_cosine"] = round(
                _cosine(centroid, profile_centroid),
                9,
            )
            row["profile_seed_reference_cosine"] = _summary(profile_scores)
        rows.append(row)

    rows.sort(
        key=lambda item: (
            -float(item["exclusive_seed_centroid_cosine"]),
            item["group_id"],
        )
    )
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostic-only comparison of a BodyRig Photoreal identity bank "
            "against private Stash performer portrait/exclusive image references."
        )
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--reference-set", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    identity_bank_path = args.identity_bank.expanduser().resolve()
    reference_set_path = args.reference_set.expanduser().resolve()
    model_root = args.model_root.expanduser().resolve()
    output = args.out.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"portrait seed diagnostic output already exists: {output}")

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    adapter = _load_adapter(repo_root)
    adapter_revision = adapter._self_revision()
    model_set = adapter.base.build_model_set(model_root)
    model_set_sha256 = _sha(
        model_set.get("model_set_sha256"),
        label="model root model-set SHA-256",
    )

    bank = _read_json(identity_bank_path, label="identity bank")
    performer_id, dimension, bank_references = _validate_bank(
        bank,
        adapter_revision=adapter_revision,
        observed_model_set_sha256=model_set_sha256,
    )
    manifest = _read_json(reference_set_path, label="Stash reference set")
    manifest_references = _validate_reference_set(
        manifest,
        performer_id=performer_id,
    )

    model_manifest = adapter.base._load_model_manifest(model_root)
    runtime = adapter.base._load_runtime(model_manifest, device=args.device)

    reference_root = reference_set_path.parent.resolve()
    seed_rows, seed_vectors = _seed_measurements(
        adapter=adapter,
        runtime=runtime,
        reference_root=reference_root,
        manifest_references=manifest_references,
        dimension=dimension,
    )
    if not seed_vectors:
        raise RuntimeError(
            "no exclusive Stash performer reference produced one unambiguous face embedding"
        )

    profile_vectors: list[list[float]] = []
    accepted_index = 0
    for row in seed_rows:
        if row.get("accepted") is not True:
            continue
        vector = seed_vectors[accepted_index]
        accepted_index += 1
        if row.get("kind") == "performer-profile":
            profile_vectors.append(vector)

    all_seed_centroid = _normalized_mean(seed_vectors)
    profile_centroid = (
        _normalized_mean(profile_vectors)
        if profile_vectors
        else None
    )
    pairwise = [
        _cosine(seed_vectors[left], seed_vectors[right])
        for left in range(len(seed_vectors))
        for right in range(left + 1, len(seed_vectors))
    ]

    groups = _group_diagnostics(
        bank_references,
        dimension=dimension,
        all_seed_centroid=all_seed_centroid,
        profile_centroid=profile_centroid,
    )

    result = {
        "format": "bodyrig-photoreal-portrait-seed-diagnostic",
        "version": 1,
        "performer_id": performer_id,
        "identity_bank_sha256": bank.get("identity_bank_sha256"),
        "adapter_revision": adapter_revision,
        "model_set_sha256": model_set_sha256,
        "reference_set_sha256": manifest.get("reference_set_sha256"),
        "exclusive_reference_count": sum(
            1
            for item in manifest_references
            if item.get("exclusive_subject") is True
        ),
        "accepted_exclusive_seed_count": len(seed_vectors),
        "accepted_profile_seed_count": len(profile_vectors),
        "seed_measurements": seed_rows,
        "exclusive_seed_pairwise_cosine": _summary(pairwise),
        "group_count": len(groups),
        "group_summaries": groups,
        "highest_seed_match_group": groups[0] if groups else None,
        "lowest_seed_match_group": groups[-1] if groups else None,
        "diagnostic_only": True,
        "identity_authority": False,
        "identity_matching_authority": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "format": result["format"],
                "performer_id": performer_id,
                "accepted_exclusive_seed_count": len(seed_vectors),
                "accepted_profile_seed_count": len(profile_vectors),
                "exclusive_seed_pairwise_cosine":
                    result["exclusive_seed_pairwise_cosine"],
                "group_count": len(groups),
                "highest_seed_match_group":
                    result["highest_seed_match_group"],
                "lowest_seed_match_group":
                    result["lowest_seed_match_group"],
                "diagnostic_only": True,
                "production_activation": False,
                "output": str(output),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
