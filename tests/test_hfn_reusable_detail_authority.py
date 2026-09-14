from pathlib import Path

import pytest

import bodyrig.hfn_reusable_detail_authority as subject
from bodyrig.hands_feet_nails_detail_candidate import HandsFeetNailsDetailCandidateError

PERSON = "person-" + "1" * 32
BODY = "body-r0001"
CAPTURE1 = "hfncap-" + "2" * 32
CAPTURE2 = "hfncap-" + "3" * 32
REV1 = "a" * 40
REV2 = "b" * 40
BODY_ID = "body-test"


def _package(tmp_path: Path) -> tuple[Path, str]:
    package = tmp_path / "source.mrbody"
    package.write_bytes(b"source package")
    return package, subject._sha256_file(package)


def _uv(root: Path, capture: str, revision: str) -> Path:
    path = root / "hands-feet-nails-uv-domain-evidence" / PERSON / BODY / capture / f"{revision}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    return path


def _install_package(monkeypatch: pytest.MonkeyPatch, package_sha: str) -> None:
    monkeypatch.setattr(subject, "_read_package", lambda path: (b"avatar", BODY_ID, package_sha))


def _authority(capture: str, revision: str, package_sha: str) -> tuple:
    source = {"source_manifest_sha256": "9" * 64}
    landmark = {"all_regions_application_ready": True}
    uv = {
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": capture,
        "uv_evidence_bodyrig_revision": revision,
        "body_id": BODY_ID,
        "package_sha256": package_sha,
    }
    return source, landmark, uv, "4" * 64, "5" * 64, "6" * 64


def test_no_existing_uv_authority_is_unresolved_without_parsing_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package, package_sha = _package(tmp_path)
    monkeypatch.setattr(subject, "_read_package", lambda path: pytest.fail("package should not be parsed without reusable evidence"))
    result = subject.resolve_reusable_detail_authority(
        tmp_path / "people", person_id=PERSON, body_revision=BODY,
        source_package_path=package, source_package_sha256=package_sha,
    )
    assert result["state"] == "unresolved"
    assert result["match_count"] == 0
    assert result["production_activation"] is False


def test_one_exact_existing_chain_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "people"
    package, package_sha = _package(tmp_path)
    uv_path = _uv(root, CAPTURE1, REV1)
    _install_package(monkeypatch, package_sha)
    monkeypatch.setattr(subject, "_load_authorities", lambda *args, **kwargs: _authority(CAPTURE1, REV1, package_sha))
    result = subject.resolve_reusable_detail_authority(
        root, person_id=PERSON, body_revision=BODY,
        source_package_path=package, source_package_sha256=package_sha,
    )
    assert result["state"] == "resolved"
    assert result["match_count"] == 1
    assert result["matches"][0]["capture_id"] == CAPTURE1
    assert result["matches"][0]["uv_evidence_path"] == str(uv_path.resolve())
    assert result["matches"][0]["source_package_sha256"] == package_sha
    assert result["human_review_required"] is True
    assert result["production_activation"] is False


def test_two_exact_existing_chains_are_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "people"
    package, package_sha = _package(tmp_path)
    _uv(root, CAPTURE1, REV1)
    _uv(root, CAPTURE2, REV2)
    _install_package(monkeypatch, package_sha)

    def load(_root, *, person_id, body_revision, capture_id, uv_evidence_file):
        return _authority(capture_id, uv_evidence_file.stem, package_sha)

    monkeypatch.setattr(subject, "_load_authorities", load)
    result = subject.resolve_reusable_detail_authority(
        root, person_id=PERSON, body_revision=BODY,
        source_package_path=package, source_package_sha256=package_sha,
    )
    assert result["state"] == "ambiguous"
    assert result["match_count"] == 2


def test_stale_or_tampered_existing_chain_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "people"
    package, package_sha = _package(tmp_path)
    _uv(root, CAPTURE1, REV1)
    _install_package(monkeypatch, package_sha)

    def stale(*args, **kwargs):
        raise HandsFeetNailsDetailCandidateError("source closeup bytes no longer match capture authority")

    monkeypatch.setattr(subject, "_load_authorities", stale)
    result = subject.resolve_reusable_detail_authority(
        root, person_id=PERSON, body_revision=BODY,
        source_package_path=package, source_package_sha256=package_sha,
    )
    assert result["state"] == "blocked"
    assert result["match_count"] == 0
    assert result["rejected_match_count"] == 1
    assert "no longer match" in result["rejected_matches"][0]["reason"]


def test_uv_for_different_package_is_blocked_not_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "people"
    package, package_sha = _package(tmp_path)
    _uv(root, CAPTURE1, REV1)
    _install_package(monkeypatch, package_sha)
    monkeypatch.setattr(subject, "_load_authorities", lambda *args, **kwargs: _authority(CAPTURE1, REV1, "7" * 64))
    result = subject.resolve_reusable_detail_authority(
        root, person_id=PERSON, body_revision=BODY,
        source_package_path=package, source_package_sha256=package_sha,
    )
    assert result["state"] == "blocked"
    assert result["match_count"] == 0
    assert "different body/package" in result["rejected_matches"][0]["reason"]


def test_changed_source_package_bytes_fail_closed_when_evidence_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "people"
    package, package_sha = _package(tmp_path)
    _uv(root, CAPTURE1, REV1)
    package.write_bytes(b"changed")
    with pytest.raises(subject.HfnReusableDetailAuthorityError, match="bytes changed"):
        subject.resolve_reusable_detail_authority(
            root, person_id=PERSON, body_revision=BODY,
            source_package_path=package, source_package_sha256=package_sha,
        )
