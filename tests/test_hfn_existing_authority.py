from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.hfn_existing_authority as subject


PERSON = "person-" + "1" * 32
BODY = "body-r0007"
BODY_ID = "body-" + "b" * 32
PACKAGE_BYTES = b"face-secondary promoted package"
PACKAGE_SHA = hashlib.sha256(PACKAGE_BYTES).hexdigest()
LANDMARK_REVISION = "a" * 40
UV_REVISION = "b" * 40
REGION_SHA = {
    "left_hand": "1" * 64,
    "right_hand": "2" * 64,
    "left_foot": "3" * 64,
    "right_foot": "4" * 64,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path, dict[str, dict]]:
    root = tmp_path / "people"
    root.mkdir()
    package = tmp_path / "face-secondary.mrbody"
    package.write_bytes(PACKAGE_BYTES)
    sources: dict[str, dict] = {}

    monkeypatch.setattr(
        subject,
        "validate_package",
        lambda _path: SimpleNamespace(manifest={"id": BODY_ID}),
    )
    monkeypatch.setattr(
        subject,
        "read_source_capture",
        lambda _root, _person, *, body_revision, capture_id: dict(sources[capture_id]),
    )
    monkeypatch.setattr(subject, "validate_uv_domain_evidence", lambda value: dict(value))
    monkeypatch.setattr(subject, "validate_landmark_evidence", lambda value: dict(value))
    return root, package, sources


def _install_chain(
    root: Path,
    sources: dict[str, dict],
    *,
    capture_id: str,
    package_sha: str = PACKAGE_SHA,
    body_id: str = BODY_ID,
    source_version: object = 1,
    tamper_landmark_hash: bool = False,
    tamper_closeup: bool = False,
) -> Path:
    capture_root = root / "hands-feet-nails-source-captures" / PERSON / BODY / capture_id
    capture_root.mkdir(parents=True)
    source_manifest = capture_root / "source-capture.json"
    source_manifest.write_text(json.dumps({"capture": capture_id}), encoding="utf-8")
    source_capture_sha = _sha(source_manifest)
    sources[capture_id] = {
        "version": source_version,
        "regions": {
            region: {"image_sha256": value}
            for region, value in REGION_SHA.items()
        },
    }

    landmark_path = subject.landmark_evidence_path(
        root,
        PERSON,
        BODY,
        capture_id,
        LANDMARK_REVISION,
    )
    landmark_path.parent.mkdir(parents=True, exist_ok=True)
    landmark_regions = {
        region: {"closeup_image_sha256": value}
        for region, value in REGION_SHA.items()
    }
    if tamper_closeup:
        landmark_regions["left_hand"] = {"closeup_image_sha256": "f" * 64}
    landmark_path.write_text(
        json.dumps({
            "person_id": PERSON,
            "body_revision": BODY,
            "capture_id": capture_id,
            "source_capture_sha256": source_capture_sha,
            "all_regions_application_ready": True,
            "regions": landmark_regions,
        }),
        encoding="utf-8",
    )
    landmark_sha = _sha(landmark_path)

    uv_path = subject.uv_evidence_path(root, PERSON, BODY, capture_id, UV_REVISION)
    uv_path.parent.mkdir(parents=True, exist_ok=True)
    uv_path.write_text(
        json.dumps({
            "person_id": PERSON,
            "body_revision": BODY,
            "capture_id": capture_id,
            "body_id": body_id,
            "package_sha256": package_sha,
            "uv_evidence_bodyrig_revision": UV_REVISION,
            "landmark_evidence_bodyrig_revision": LANDMARK_REVISION,
            "landmark_evidence_sha256": "e" * 64 if tamper_landmark_hash else landmark_sha,
        }),
        encoding="utf-8",
    )
    return uv_path


def test_unique_exact_existing_chain_is_reusable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, package, sources = _setup(monkeypatch, tmp_path)
    capture = "hfncap-" + "2" * 32
    uv_path = _install_chain(root, sources, capture_id=capture)

    matches = subject.find_reusable_hfn_source_uv_authorities(
        root,
        PERSON,
        body_revision=BODY,
        package_path=package,
        package_sha256=PACKAGE_SHA,
    )

    assert len(matches) == 1
    assert matches[0]["capture_id"] == capture
    assert matches[0]["uv_evidence_path"] == str(uv_path.resolve())
    assert matches[0]["uv_evidence_sha256"] == _sha(uv_path)
    assert matches[0]["body_id"] == BODY_ID
    assert matches[0]["package_sha256"] == PACKAGE_SHA


def test_no_existing_chain_returns_no_reuse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, package, _sources = _setup(monkeypatch, tmp_path)
    assert subject.find_reusable_hfn_source_uv_authorities(
        root,
        PERSON,
        body_revision=BODY,
        package_path=package,
        package_sha256=PACKAGE_SHA,
    ) == []


def test_multiple_valid_chains_remain_ambiguous(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, package, sources = _setup(monkeypatch, tmp_path)
    _install_chain(root, sources, capture_id="hfncap-" + "2" * 32)
    _install_chain(root, sources, capture_id="hfncap-" + "3" * 32)

    matches = subject.find_reusable_hfn_source_uv_authorities(
        root,
        PERSON,
        body_revision=BODY,
        package_path=package,
        package_sha256=PACKAGE_SHA,
    )
    assert len(matches) == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"package_sha": "9" * 64},
        {"body_id": "body-" + "c" * 32},
        {"tamper_landmark_hash": True},
        {"tamper_closeup": True},
        {"source_version": True},
    ],
)
def test_stale_tampered_or_noncanonical_authority_does_not_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kwargs: dict,
) -> None:
    root, package, sources = _setup(monkeypatch, tmp_path)
    _install_chain(root, sources, capture_id="hfncap-" + "2" * 32, **kwargs)

    assert subject.find_reusable_hfn_source_uv_authorities(
        root,
        PERSON,
        body_revision=BODY,
        package_path=package,
        package_sha256=PACKAGE_SHA,
    ) == []


def test_discovery_fails_closed_if_exact_package_bytes_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, package, sources = _setup(monkeypatch, tmp_path)
    _install_chain(root, sources, capture_id="hfncap-" + "2" * 32)
    package.write_bytes(b"changed")

    with pytest.raises(subject.HfnExistingAuthorityError, match="package bytes changed"):
        subject.find_reusable_hfn_source_uv_authorities(
            root,
            PERSON,
            body_revision=BODY,
            package_path=package,
            package_sha256=PACKAGE_SHA,
        )
