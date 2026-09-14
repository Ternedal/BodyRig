from pathlib import Path

import pytest

import bodyrig.hfn_identity_binding as subject
from bodyrig.person_voice_source import PersonVoiceSourceError

BODY_ID = "body-test"
PACKAGE_SHA = "1" * 64
P1 = "person-" + "a" * 32
P2 = "person-" + "b" * 32


def _profile(person_id: str, *, body_revision: str = "body-r0001", package_sha: str = PACKAGE_SHA) -> dict:
    return {
        "person_id": person_id,
        "source": {
            "kind": "stash-performer",
            "performer_id": "performer-1",
            "performer_name": "Performer",
            "disambiguation": "",
        },
        "body_revisions": [
            {
                "revision_id": body_revision,
                "body_id": BODY_ID,
                "package_sha256": package_sha,
            }
        ],
    }


def _source(*args, **kwargs) -> dict:
    return {
        "manifest_sha256": "2" * 64,
        "source_files": [{"scene_id": "scene-1", "name": "one.mp4", "sha256": "3" * 64, "path": "/source/one.mp4"}],
    }


def _install_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profiles: dict[str, dict]) -> None:
    for person_id in profiles:
        (tmp_path / f"{person_id}.json").write_text("{}\n", encoding="utf-8")

    def fake_load(root, person_id):
        return profiles[person_id]

    monkeypatch.setattr(subject, "load_profile", fake_load)


def test_unique_source_authoritative_match_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_profiles(tmp_path, monkeypatch, {P1: _profile(P1)})
    monkeypatch.setattr(subject, "source_files_for_body", _source)
    result = subject.resolve_hfn_identity(tmp_path, body_id=BODY_ID, package_sha256=PACKAGE_SHA)
    assert result["state"] == "resolved"
    assert result["metadata_match_count"] == 1
    assert result["match_count"] == 1
    assert result["rejected_match_count"] == 0
    assert result["matches"] == [{
        "person_id": P1,
        "body_revision": "body-r0001",
        "source_manifest_sha256": "2" * 64,
        "source_file_count": 1,
    }]
    assert result["source_authority_required"] is True
    assert result["human_review_required"] is True
    assert result["production_activation"] is False


def test_no_exact_body_package_match_is_unresolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_profiles(tmp_path, monkeypatch, {P1: _profile(P1, package_sha="4" * 64)})
    monkeypatch.setattr(subject, "source_files_for_body", _source)
    result = subject.resolve_hfn_identity(tmp_path, body_id=BODY_ID, package_sha256=PACKAGE_SHA)
    assert result["state"] == "unresolved"
    assert result["metadata_match_count"] == 0
    assert result["match_count"] == 0
    assert result["matches"] == []


def test_multiple_source_authoritative_matches_are_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_profiles(tmp_path, monkeypatch, {P1: _profile(P1), P2: _profile(P2)})
    monkeypatch.setattr(subject, "source_files_for_body", _source)
    result = subject.resolve_hfn_identity(tmp_path, body_id=BODY_ID, package_sha256=PACKAGE_SHA)
    assert result["state"] == "ambiguous"
    assert result["metadata_match_count"] == 2
    assert result["match_count"] == 2


def test_stale_or_tampered_source_binding_blocks_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_profiles(tmp_path, monkeypatch, {P1: _profile(P1)})

    def stale(*args, **kwargs):
        raise PersonVoiceSourceError("body source file bytes no longer match its source binding")

    monkeypatch.setattr(subject, "source_files_for_body", stale)
    result = subject.resolve_hfn_identity(tmp_path, body_id=BODY_ID, package_sha256=PACKAGE_SHA)
    assert result["state"] == "blocked"
    assert result["metadata_match_count"] == 1
    assert result["match_count"] == 0
    assert result["rejected_match_count"] == 1
    assert "no longer match" in result["rejected_matches"][0]["reason"]


def test_exactly_one_valid_match_wins_over_rejected_stale_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_profiles(tmp_path, monkeypatch, {P1: _profile(P1), P2: _profile(P2)})

    def source_for(root, profile, *, body_revision):
        if profile["person_id"] == P2:
            raise PersonVoiceSourceError("source binding missing")
        return _source()

    monkeypatch.setattr(subject, "source_files_for_body", source_for)
    result = subject.resolve_hfn_identity(tmp_path, body_id=BODY_ID, package_sha256=PACKAGE_SHA)
    assert result["state"] == "resolved"
    assert result["metadata_match_count"] == 2
    assert result["match_count"] == 1
    assert result["rejected_match_count"] == 1
    assert result["matches"][0]["person_id"] == P1


def test_profile_filename_must_match_canonical_person_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    filename_person = P1
    _install_profiles(tmp_path, monkeypatch, {filename_person: _profile(P2)})
    monkeypatch.setattr(subject, "source_files_for_body", _source)
    result = subject.resolve_hfn_identity(tmp_path, body_id=BODY_ID, package_sha256=PACKAGE_SHA)
    assert result["state"] == "unresolved"
    assert result["metadata_match_count"] == 0


def test_invalid_inputs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(subject.HfnIdentityBindingError, match="body_id"):
        subject.resolve_hfn_identity(tmp_path, body_id="BAD BODY", package_sha256=PACKAGE_SHA)
    with pytest.raises(subject.HfnIdentityBindingError, match="package_sha256"):
        subject.resolve_hfn_identity(tmp_path, body_id=BODY_ID, package_sha256="not-a-sha")
