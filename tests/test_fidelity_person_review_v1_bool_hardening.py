from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.person_body_review import (
    CANONICAL_VIEWS,
    PersonBodyReviewError,
    persist_review,
    read_review_by_package,
    validate_fidelity_output,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fidelity_output(
    tmp_path: Path,
    *,
    body_id: str,
    package_sha256: str,
    comparison_version: int | float | bool = 1,
    manifest_version: int | float | bool = 1,
) -> Path:
    root = tmp_path / "fidelity"
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)
    entries = []
    for view in CANONICAL_VIEWS:
        payload = b"\x89PNG\r\n\x1a\nbodyrig-v1-hardening-" + view.encode("ascii")
        path = snapshots / f"{view}.png"
        path.write_bytes(payload)
        entries.append(
            {
                "view": view,
                "file": f"{view}.png",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "width": 1024,
                "height": 1024,
            }
        )
    _write_json(
        snapshots / "fidelity-render-set.json",
        {
            "format": "bodyrig-fidelity-render-set",
            "version": manifest_version,
            "body_id": body_id,
            "package_sha256": package_sha256,
            "semantics": "visual-fidelity-not-identity-verification",
            "snapshots": entries,
        },
    )
    _write_json(
        root / "comparison-authority.json",
        {
            "format": "bodyrig-fidelity-comparison-authority",
            "version": comparison_version,
            "authority": "gate-a-pending-candidate",
            "bodyrig_revision": "a" * 40,
            "runtime_manifest_sha256": "b" * 64,
            "package_sha256": package_sha256,
            "physical_acceptance_authority": True,
            "comparison_only": True,
            "production_activation": False,
        },
    )
    return root


@pytest.mark.parametrize(
    ("comparison_version", "manifest_version", "message"),
    [
        (True, 1, "comparison authority format/version mismatch"),
        (1, True, "render-set format/version mismatch"),
    ],
)
def test_person_body_review_rejects_boolean_input_versions(
    tmp_path: Path,
    comparison_version: int | float | bool,
    manifest_version: int | float | bool,
    message: str,
) -> None:
    body_id = "bodyid-" + "1" * 24
    package_sha = "2" * 64
    source = _fidelity_output(
        tmp_path,
        body_id=body_id,
        package_sha256=package_sha,
        comparison_version=comparison_version,
        manifest_version=manifest_version,
    )
    with pytest.raises(PersonBodyReviewError, match=message):
        validate_fidelity_output(source, body_id=body_id, package_sha256=package_sha)


def test_person_body_review_accepts_numeric_one_point_zero_versions(tmp_path: Path) -> None:
    body_id = "bodyid-" + "3" * 24
    package_sha = "4" * 64
    source = _fidelity_output(
        tmp_path,
        body_id=body_id,
        package_sha256=package_sha,
        comparison_version=1.0,
        manifest_version=1.0,
    )
    validated = validate_fidelity_output(source, body_id=body_id, package_sha256=package_sha)
    assert validated["package_sha256"] == package_sha


def test_persisted_person_body_review_rejects_boolean_receipt_version(tmp_path: Path) -> None:
    person_id = "person-" + "5" * 32
    body_id = "bodyid-" + "6" * 24
    package_sha = "7" * 64
    source = _fidelity_output(tmp_path, body_id=body_id, package_sha256=package_sha)
    library = tmp_path / "people"
    persist_review(
        library,
        person_id=person_id,
        fidelity_output_dir=source,
        body_id=body_id,
        package_sha256=package_sha,
    )
    receipt = library / ".body-reviews" / person_id / package_sha / "review.json"
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["version"] = True
    _write_json(receipt, value)
    with pytest.raises(PersonBodyReviewError, match="body review receipt format/fields mismatch"):
        read_review_by_package(library, person_id=person_id, package_sha256=package_sha)


def test_fidelity_renderer_uses_bool_safe_v1_authority_for_all_direct_versions() -> None:
    source = (ROOT / "run-fidelity-windows-render-probe.ps1").read_text(encoding="utf-8")
    assert "function Test-V1Version" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    for expression in (
        "$acceptance.version",
        "$reviewAuthority.version",
        "$runtime.version",
        "$probe.version",
        "$deformation.version",
        "$hairDeformation.version",
        "$manifest.version",
    ):
        assert f"Test-V1Version {expression}" in source
        assert f"[int]{expression}" not in source
    assert '[string]$probe.format -ne "bodyrig-renderer-probe"' in source
    assert '[string]$deformation.format -ne "bodyrig-deformation-probe"' in source
    assert "physical_acceptance_authority = $usingAcceptance" in source
    assert "comparison_only = $true" in source
    assert "production_activation = $false" in source
