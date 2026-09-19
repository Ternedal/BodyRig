from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_portrait_seed_diagnostic.py"
SPEC = importlib.util.spec_from_file_location(
    "bodyrig_photoreal_portrait_seed_diagnostic_test",
    TOOL,
)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def _manifest() -> dict[str, object]:
    core = {
        "format": "bodyrig-fidelity-reference-set",
        "version": 1,
        "performer": {"id": "42", "name": "Performer 42", "disambiguation": ""},
        "stash_version": "v0.31.1",
        "references": [
            {
                "kind": "performer-profile",
                "stash_id": "42",
                "performer_count": 1,
                "exclusive_subject": True,
                "file": "reference-01.jpg",
                "sha256": "a" * 64,
                "byte_count": 100,
            }
        ],
        "privacy": {
            "contains_source_media": True,
            "private_workspace_only": True,
        },
        "semantics": "visual-fidelity-not-identity-verification",
    }
    canonical = json.dumps(
        core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        **core,
        "reference_set_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def test_reference_set_validation_requires_exact_performer_and_digest() -> None:
    manifest = _manifest()

    refs = diagnostic._validate_reference_set(manifest, performer_id="42")

    assert len(refs) == 1
    assert refs[0]["kind"] == "performer-profile"

    broken = dict(manifest)
    broken["reference_set_sha256"] = "b" * 64
    with pytest.raises(RuntimeError, match="manifest digest mismatch"):
        diagnostic._validate_reference_set(broken, performer_id="42")


def test_group_diagnostic_ranks_seed_consistent_group_first() -> None:
    seed = [1.0, 0.0, 0.0, 0.0]
    groups = diagnostic._group_diagnostics(
        [
            {
                "group_id": "scene:good",
                "source_key": "scene:good:E:/good.mp4",
                "embedding": [1.0, 0.0, 0.0, 0.0],
            },
            {
                "group_id": "scene:good",
                "source_key": "scene:good:E:/good.mp4",
                "embedding": [0.99, 0.1, 0.0, 0.0],
            },
            {
                "group_id": "scene:other",
                "source_key": "scene:other:E:/other.mp4",
                "embedding": [0.0, 1.0, 0.0, 0.0],
            },
        ],
        dimension=4,
        all_seed_centroid=seed,
        profile_centroid=seed,
    )

    assert [item["group_id"] for item in groups] == [
        "scene:good",
        "scene:other",
    ]
    assert groups[0]["exclusive_seed_centroid_cosine"] > 0.99
    assert groups[1]["exclusive_seed_centroid_cosine"] == 0.0
    assert groups[0]["profile_seed_centroid_cosine"] > 0.99


def test_summary_is_threshold_free_and_handles_singletons() -> None:
    assert diagnostic._summary([]) is None
    assert diagnostic._summary([0.25]) == {
        "min": 0.25,
        "median": 0.25,
        "max": 0.25,
    }
    assert diagnostic._summary([0.1, 0.5, 0.9]) == {
        "min": 0.1,
        "median": 0.5,
        "max": 0.9,
    }
