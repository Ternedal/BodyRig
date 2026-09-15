from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-teacher-benchmark-registry"
VERSION = 1

# Registry entries describe reproducible comparison candidates. They do not
# authorize source disclosure, training, photoreal acceptance, runtime use or
# production. Licensing posture is deliberately conservative: a permissive
# top-level repository license does not override restrictions in model assets,
# submodules or inherited renderer code.
BENCHMARKS: tuple[dict[str, Any], ...] = (
    {
        "benchmark": "exavatar",
        "priority": 1,
        "upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "upstream_ref": "d45268730c779fae4118f1a361cf9ff639bc4d1e",
        "representation": "smplx-conditioned-3d-gaussians",
        "custom_monocular_video": True,
        "full_body": True,
        "face_and_hands": True,
        "explicit_female_geometry_prior": True,
        "teacher_adapter_status": "implemented",
        "real_time_runtime_code_required_for_teacher": False,
        "license_posture": "benchmark-dependencies-require-audit",
        "production_dependency_authorized": False,
        "known_method_caveats": [
            "upstream avatar config defaults to male and comments that the female version is not very good",
            "public custom workflow is fundamentally a single-video benchmark rather than whole-Stash reconstruction",
        ],
        "notes": "Primary first executable benchmark because the public custom-video path includes SMPL-X fitting, face, hands and full body; upstream avatar defaults are patched explicitly by BodyRig.",
    },
    {
        "benchmark": "gaussianavatar",
        "priority": 2,
        "upstream_repository": "https://github.com/aipixel/GaussianAvatar",
        "upstream_ref": "d981c62238ef64e89dcc04719d2ebbb4758b080a",
        "representation": "animatable-3d-gaussians",
        "custom_monocular_video": True,
        "full_body": True,
        "face_and_hands": False,
        "explicit_female_geometry_prior": True,
        "teacher_adapter_status": "planned",
        "real_time_runtime_code_required_for_teacher": False,
        "license_posture": "top-level-mit-dependency-audit-required",
        "production_dependency_authorized": False,
        "known_method_caveats": [
            "public README still marks real-time animation code as unreleased",
            "own-video preprocessing depends on external InstantAvatar tooling and model assets",
            "top-level MIT license does not by itself clear inherited renderer/model dependencies for production",
        ],
        "notes": "Independent female-capable full-body comparator. Public code exposes smpl_gender and ships own-video training scripts with SMPL/SMPL-X female, male and neutral asset layout.",
    },
    {
        "benchmark": "splattingavatar",
        "priority": 3,
        "upstream_repository": "https://github.com/initialneil/SplattingAvatar",
        "upstream_ref": "8cf2c7cdcf1defb4089e1911f36224258ecd869f",
        "representation": "mesh-embedded-3d-gaussians",
        "custom_monocular_video": True,
        "full_body": True,
        "face_and_hands": False,
        "explicit_female_geometry_prior": True,
        "teacher_adapter_status": "research-comparator-planned",
        "real_time_runtime_code_required_for_teacher": False,
        "license_posture": "research-noncommercial-only",
        "production_dependency_authorized": False,
        "known_method_caveats": [
            "code-bearing implementation is on the pinned neil-dev branch rather than current master",
            "license explicitly restricts code to noncommercial use without permission",
            "published experiments used an RTX 3090 24GB; lower-memory operation requires an explicit Gaussian cap",
        ],
        "notes": "Research-only comparator. Full-body PeopleSnapshot examples include female subjects and the representation is explicitly designed for realistic real-time mesh-embedded Gaussian rendering.",
    },
)


class PhotorealTeacherBenchmarkRegistryError(ValueError):
    pass


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_benchmark_registry() -> dict[str, Any]:
    entries = [dict(item) for item in BENCHMARKS]
    ids = [str(item["benchmark"]) for item in entries]
    priorities = [int(item["priority"]) for item in entries]
    if len(ids) != len(set(ids)):
        raise PhotorealTeacherBenchmarkRegistryError("teacher benchmark registry repeats benchmark id")
    if priorities != sorted(priorities) or len(priorities) != len(set(priorities)):
        raise PhotorealTeacherBenchmarkRegistryError("teacher benchmark priorities are invalid")
    for entry in entries:
        ref = str(entry.get("upstream_ref") or "").lower()
        if len(ref) != 40 or any(ch not in "0123456789abcdef" for ch in ref):
            raise PhotorealTeacherBenchmarkRegistryError(f"benchmark upstream ref is not an exact Git commit: {entry.get('benchmark')}")
        if entry.get("production_dependency_authorized") is not False:
            raise PhotorealTeacherBenchmarkRegistryError("benchmark registry cannot authorize production dependency")
        caveats = entry.get("known_method_caveats")
        if not isinstance(caveats, list) or not caveats:
            raise PhotorealTeacherBenchmarkRegistryError(f"benchmark caveat inventory is empty: {entry.get('benchmark')}")
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "benchmarks": entries,
        "benchmark_count": len(entries),
        "comparison_policy": "same-authorized-training-universe-and-external-held-out-eval-v1",
        "benchmark_success_is_photoreal_acceptance": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["benchmark_registry_sha256"] = _digest(result)
    return result


def benchmark_by_id(benchmark: str) -> dict[str, Any]:
    target = str(benchmark or "").strip().lower()
    registry = build_benchmark_registry()
    for entry in registry["benchmarks"]:
        if entry["benchmark"] == target:
            return dict(entry)
    raise PhotorealTeacherBenchmarkRegistryError(f"unknown photoreal teacher benchmark: {target or '<empty>'}")
