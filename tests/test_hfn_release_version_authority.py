from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import hands_feet_nails_release_authority as release


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
REVISION = "a" * 40
PACKAGE_SHA = "b" * 64
RUNTIME_SHA = "c" * 64
MANIFEST_SHA = "d" * 64
RELEASE_ID = "hfnrelease-" + "1" * 32
REVIEW_ID = "hfnreview-" + "2" * 32


def _review() -> dict[str, Any]:
    regions = {region: (str(index % 10) * 64) for index, region in enumerate(release.REQUIRED_REGIONS, start=1)}
    return {
        "bodyrig_revision": REVISION,
        "body_id": "body-test",
        "body_package_sha256": PACKAGE_SHA,
        "render_manifest_sha256": MANIFEST_SHA,
        "render_region_sha256": regions,
    }


def _comparison(version: Any) -> dict[str, Any]:
    return {
        "format": "bodyrig-fidelity-comparison-authority",
        "version": version,
        "authority": "validated-package-comparison-only",
        "bodyrig_revision": REVISION,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "package_sha256": PACKAGE_SHA,
        "physical_acceptance_authority": False,
        "comparison_only": True,
        "production_activation": False,
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_hfn_comparison_authority_rejects_boolean_non_numeric_and_wrong_v1(version: Any) -> None:
    with pytest.raises(
        release.HandsFeetNailsReleaseAuthorityError,
        match="M2 comparison authority format/version mismatch",
    ):
        release._validate_comparison(_comparison(version), review=_review())


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_hfn_comparison_authority_preserves_numeric_v1(version: Any) -> None:
    value = release._validate_comparison(_comparison(version), review=_review())

    assert value["package_sha256"] == PACKAGE_SHA
    assert value["runtime_manifest_sha256"] == RUNTIME_SHA


def _write_render_bundle(tmp_path: Path, version: Any) -> tuple[Path, dict[str, Any]]:
    review = _review()
    comparison_path = tmp_path / "comparison-authority.json"
    comparison_path.write_text(json.dumps(_comparison(1), sort_keys=True), encoding="utf-8")
    render_path = tmp_path / "hands-feet-nails-render-authority.json"
    render = {
        "format": release.RENDER_AUTHORITY_FORMAT,
        "version": version,
        "bodyrig_revision": REVISION,
        "body_id": review["body_id"],
        "package_sha256": PACKAGE_SHA,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "comparison_authority_sha256": release._sha256_file(comparison_path),
        "render_manifest_sha256": MANIFEST_SHA,
        "render_region_sha256": dict(review["render_region_sha256"]),
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }
    render_path.write_text(json.dumps(render, sort_keys=True), encoding="utf-8")
    return render_path, review


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_hfn_render_authority_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    render_path, review = _write_render_bundle(tmp_path, version)
    monkeypatch.setattr(
        release,
        "validate_render_manifest",
        lambda *_args, **_kwargs: {
            "manifest_sha256": MANIFEST_SHA,
            "region_sha256": dict(review["render_region_sha256"]),
        },
    )

    with pytest.raises(
        release.HandsFeetNailsReleaseAuthorityError,
        match="M2 render authority format/version mismatch",
    ):
        release._validate_render_authority_bundle(render_path, review=review)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_hfn_render_authority_preserves_numeric_v1_and_review_only_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    render_path, review = _write_render_bundle(tmp_path, version)
    monkeypatch.setattr(
        release,
        "validate_render_manifest",
        lambda *_args, **_kwargs: {
            "manifest_sha256": MANIFEST_SHA,
            "region_sha256": dict(review["render_region_sha256"]),
        },
    )

    value = release._validate_render_authority_bundle(render_path, review=review)

    assert value["runtime_manifest_sha256"] == RUNTIME_SHA
    assert value["render_manifest_sha256"] == MANIFEST_SHA
    assert value["render_region_sha256"] == review["render_region_sha256"]
    assert value["value"]["comparison_only"] is True
    assert value["value"]["human_review_required"] is True
    assert value["value"]["production_activation"] is False


def _release_authority(version: Any) -> dict[str, Any]:
    source_regions = {region: "e" * 64 for region in release.REQUIRED_REGIONS}
    render_regions = {region: "f" * 64 for region in release.REQUIRED_REGIONS}
    return {
        "format": release.FORMAT,
        "version": version,
        "policy_revision": release.POLICY_REVISION,
        "release_id": RELEASE_ID,
        "review_id": REVIEW_ID,
        "person_id": "person-test",
        "person_revision": "person-r0001",
        "assembly_fingerprint": "0" * 64,
        "body_revision": "body-r0001",
        "body_id": "body-test",
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "review_authority_sha256": "1" * 64,
        "source_capture_id": "capture-test",
        "source_capture_sha256": "2" * 64,
        "source_manifest_sha256": "3" * 64,
        "source_region_sha256": source_regions,
        "render_authority_sha256": "4" * 64,
        "comparison_authority_sha256": "5" * 64,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "render_manifest_sha256": MANIFEST_SHA,
        "render_region_sha256": render_regions,
        "finalized_utc": "2026-09-14T18:00:00Z",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **{field: True for field in release.CHECKLIST_FIELDS},
        "production_activation": False,
    }


def _bind_release_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    assembly = {
        "person_id": "person-test",
        "person_revision": "person-r0001",
        "assembly_fingerprint": "0" * 64,
        "body_revision": "body-r0001",
        "body_id": "body-test",
    }
    monkeypatch.setattr(release, "_assembly_identity", lambda _receipt: dict(assembly))
    monkeypatch.setattr(release, "_release_identity", lambda _status, _assembly: {"package_sha256": PACKAGE_SHA})
    monkeypatch.setattr(release, "_release_id", lambda **_kwargs: RELEASE_ID)


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_final_hfn_release_authority_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    _bind_release_identity(monkeypatch)

    with pytest.raises(
        release.HandsFeetNailsReleaseAuthorityError,
        match="hands/feet/nails finalized authority format/version/policy mismatch",
    ):
        release.validate_release_authority_structure(
            _release_authority(version),
            assembly_receipt={},
            body_release_status={},
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_final_hfn_release_authority_preserves_numeric_v1_and_non_production_semantics(
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    _bind_release_identity(monkeypatch)

    value = release.validate_release_authority_structure(
        _release_authority(version),
        assembly_receipt={},
        body_release_status={},
    )

    assert value["version"] == version
    assert value["state"] == "complete"
    assert value["source_grounded"] is True
    assert value["operator_supplied"] is True
    assert all(value[field] is True for field in release.CHECKLIST_FIELDS)
    assert value["production_activation"] is False


def _bind_frozen_readback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> dict[str, Any]:
    _bind_release_identity(monkeypatch)
    target = tmp_path / "frozen-release"
    target.mkdir()
    (target / "authority.json").write_text("{}\n", encoding="utf-8")

    review_dir = tmp_path / "review-authority"
    review_dir.mkdir()
    review_path = review_dir / "authority.json"
    review_path.write_text("review-authority\n", encoding="utf-8")

    comparison_path = target / "comparison-authority.json"
    comparison_path.write_text(json.dumps(_comparison(1), sort_keys=True), encoding="utf-8")

    value = _release_authority(1)
    value["review_authority_sha256"] = release._sha256_file(review_path)
    value["comparison_authority_sha256"] = release._sha256_file(comparison_path)

    render_value = {
        "format": release.RENDER_AUTHORITY_FORMAT,
        "version": version,
        "bodyrig_revision": REVISION,
        "body_id": value["body_id"],
        "package_sha256": PACKAGE_SHA,
        "runtime_manifest_sha256": RUNTIME_SHA,
        "comparison_authority_sha256": value["comparison_authority_sha256"],
        "render_manifest_sha256": MANIFEST_SHA,
        "render_region_sha256": dict(value["render_region_sha256"]),
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }
    render_path = target / "render-authority.json"
    render_path.write_text(json.dumps(render_value, sort_keys=True), encoding="utf-8")
    value["render_authority_sha256"] = release._sha256_file(render_path)

    review = {
        "review_id": REVIEW_ID,
        "person_id": value["person_id"],
        "person_revision": value["person_revision"],
        "assembly_fingerprint": value["assembly_fingerprint"],
        "body_revision": value["body_revision"],
        "body_id": value["body_id"],
        "body_package_sha256": value["body_package_sha256"],
        "bodyrig_revision": value["bodyrig_revision"],
        "source_capture_id": value["source_capture_id"],
        "source_capture_sha256": value["source_capture_sha256"],
        "source_manifest_sha256": value["source_manifest_sha256"],
        "source_region_sha256": dict(value["source_region_sha256"]),
        "render_manifest_sha256": value["render_manifest_sha256"],
        "render_region_sha256": dict(value["render_region_sha256"]),
    }

    monkeypatch.setattr(release, "release_authority_dir", lambda *_args, **_kwargs: target)
    monkeypatch.setattr(release, "validate_release_authority_structure", lambda *_args, **_kwargs: dict(value))
    monkeypatch.setattr(release, "read_authority", lambda *_args, **_kwargs: dict(review))
    monkeypatch.setattr(release, "review_authority_dir", lambda *_args, **_kwargs: review_dir)
    return value


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_frozen_hfn_render_readback_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    _bind_frozen_readback(monkeypatch, tmp_path, version)

    with pytest.raises(
        release.HandsFeetNailsReleaseAuthorityError,
        match="frozen M2 render authority is invalid",
    ):
        release.read_release_authority(
            tmp_path,
            assembly_receipt={},
            body_release_status={},
            release_id=RELEASE_ID,
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_frozen_hfn_render_readback_preserves_numeric_v1_and_non_production_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: Any,
) -> None:
    expected = _bind_frozen_readback(monkeypatch, tmp_path, version)

    value = release.read_release_authority(
        tmp_path,
        assembly_receipt={},
        body_release_status={},
        release_id=RELEASE_ID,
    )

    assert value == expected
    assert value["state"] == "complete"
    assert value["source_grounded"] is True
    assert value["operator_supplied"] is True
    assert value["production_activation"] is False
