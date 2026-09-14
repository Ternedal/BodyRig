from pathlib import Path

CONTINUATION = Path("bodyrig/high_fidelity_hfn_continuation.py")
EXECUTOR = Path("bodyrig/fidelity_component_gap_executor.py")
MODULE = Path("bodyrig/hfn_reusable_detail_authority.py")
MODULE_TEST = Path("tests/test_hfn_reusable_detail_authority.py")
CONT_TEST = Path("tests/test_high_fidelity_hfn_continuation.py")
EXEC_TEST = Path("tests/test_fidelity_component_gap_executor.py")


MODULE.write_text(r'''from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    _load_authorities,
    _read_package,
)

FORMAT = "bodyrig-hfn-reusable-detail-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-hfn-reusable-detail-authority-v1"
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_RE = re.compile(r"^body-r[0-9]{4}$")
CAPTURE_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class HfnReusableDetailAuthorityError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(person_id: str, body_revision: str) -> tuple[str, str]:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_RE.fullmatch(body):
        raise HfnReusableDetailAuthorityError("HFN reusable authority identity is not canonical")
    return person, body


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise HfnReusableDetailAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _result(
    *,
    person_id: str,
    body_revision: str,
    source_package_sha256: str,
    body_id: str | None,
    state: str,
    evidence_file_count: int,
    matches: list[dict[str, Any]],
    rejected: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "person_id": person_id,
        "body_revision": body_revision,
        "body_id": body_id,
        "source_package_sha256": source_package_sha256,
        "state": state,
        "evidence_file_count": evidence_file_count,
        "match_count": len(matches),
        "rejected_match_count": len(rejected),
        "matches": matches,
        "rejected_matches": rejected,
        "source_authority_required": True,
        "human_review_required": True,
        "production_activation": False,
    }


def resolve_reusable_detail_authority(
    root: str | Path,
    *,
    person_id: str,
    body_revision: str,
    source_package_path: str | Path,
    source_package_sha256: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person, body = _identity(person_id, body_revision)
    expected_package_sha = _sha(source_package_sha256, label="HFN source package SHA-256")
    base = root_path / "hands-feet-nails-uv-domain-evidence" / person / body
    if not base.is_dir():
        return _result(
            person_id=person,
            body_revision=body,
            source_package_sha256=expected_package_sha,
            body_id=None,
            state="unresolved",
            evidence_file_count=0,
            matches=[],
            rejected=[],
        )
    if base.is_symlink():
        raise HfnReusableDetailAuthorityError("HFN UV authority root is symlinked")

    package = Path(source_package_path).expanduser().resolve()
    if not package.is_file() or package.is_symlink():
        raise HfnReusableDetailAuthorityError("HFN exact source package is missing or symlinked")
    if _sha256_file(package) != expected_package_sha:
        raise HfnReusableDetailAuthorityError("HFN exact source package bytes changed before authority reuse")
    try:
        _avatar, body_id, package_sha = _read_package(package)
    except HandsFeetNailsDetailCandidateError as exc:
        raise HfnReusableDetailAuthorityError(str(exc)) from exc
    if package_sha != expected_package_sha or not str(body_id or "").strip():
        raise HfnReusableDetailAuthorityError("HFN source package validation disagrees with exact package authority")

    evidence_files = sorted(base.glob("*/*.json"))
    matches: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for uv_path in evidence_files:
        capture_id = uv_path.parent.name.lower()
        uv_revision = uv_path.stem.lower()
        reject_identity = {"capture_id": capture_id, "uv_evidence_path": str(uv_path.resolve())}
        if uv_path.is_symlink() or uv_path.parent.is_symlink():
            rejected.append({**reject_identity, "reason": "UV evidence path is symlinked"})
            continue
        if not CAPTURE_RE.fullmatch(capture_id) or not GIT_RE.fullmatch(uv_revision):
            rejected.append({**reject_identity, "reason": "UV evidence path identity is not canonical"})
            continue
        try:
            source, landmark, uv, source_capture_sha, landmark_sha, uv_sha = _load_authorities(
                root_path,
                person_id=person,
                body_revision=body,
                capture_id=capture_id,
                uv_evidence_file=uv_path,
            )
        except HandsFeetNailsDetailCandidateError as exc:
            rejected.append({**reject_identity, "reason": str(exc)})
            continue
        if (
            uv.get("person_id") != person
            or uv.get("body_revision") != body
            or uv.get("capture_id") != capture_id
            or uv.get("uv_evidence_bodyrig_revision") != uv_revision
        ):
            rejected.append({**reject_identity, "reason": "UV evidence path/identity no longer matches its strict authority"})
            continue
        if uv.get("body_id") != body_id or uv.get("package_sha256") != expected_package_sha:
            rejected.append({**reject_identity, "reason": "UV evidence targets different body/package bytes"})
            continue
        if landmark.get("all_regions_application_ready") is not True:
            rejected.append({**reject_identity, "reason": "linked landmark evidence is not application-ready"})
            continue
        source_manifest = str(source.get("source_manifest_sha256") or "").lower()
        if source_manifest and not SHA_RE.fullmatch(source_manifest):
            rejected.append({**reject_identity, "reason": "source capture manifest authority is invalid"})
            continue
        matches.append({
            "person_id": person,
            "body_revision": body,
            "body_id": body_id,
            "capture_id": capture_id,
            "uv_evidence_bodyrig_revision": uv_revision,
            "uv_evidence_path": str(uv_path.resolve()),
            "uv_evidence_sha256": uv_sha,
            "source_capture_sha256": source_capture_sha,
            "landmark_evidence_sha256": landmark_sha,
            "source_package_sha256": expected_package_sha,
        })

    if len(matches) == 1:
        state = "resolved"
    elif len(matches) > 1:
        state = "ambiguous"
    elif evidence_files:
        state = "blocked"
    else:
        state = "unresolved"
    return _result(
        person_id=person,
        body_revision=body,
        source_package_sha256=expected_package_sha,
        body_id=str(body_id),
        state=state,
        evidence_file_count=len(evidence_files),
        matches=matches,
        rejected=rejected,
    )
''', encoding="utf-8", newline="\n")

MODULE_TEST.write_text(r'''from pathlib import Path

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
''', encoding="utf-8", newline="\n")

text = CONTINUATION.read_text(encoding="utf-8")
anchor = '''from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    read_detail_candidate,
)
'''
addition = anchor + '''from .hfn_reusable_detail_authority import (
    HfnReusableDetailAuthorityError,
    resolve_reusable_detail_authority,
)
'''
if text.count(anchor) != 1:
    raise SystemExit("continuation detail import anchor mismatch")
text = text.replace(anchor, addition, 1)
start = text.index("    if detail is None:\n")
end = text.index("\n    geometry_package, geometry_receipt = geometry_paths(", start)
new_block = r'''    if detail is None:
        try:
            reusable = resolve_reusable_detail_authority(
                root,
                person_id=person_id,
                body_revision=body_revision,
                source_package_path=source_package_path,
                source_package_sha256=source_package_sha256,
            )
        except HfnReusableDetailAuthorityError as exc:
            gates.append(_gate(CANDIDATE_GATE, "invalid", reason=f"HFN reusable source/UV authority is invalid: {exc}"))
            return {"gates": gates, "actions": actions, "package_path": source_package_path, "package_sha256": source_package_sha256}
        if reusable["state"] == "resolved":
            match = reusable["matches"][0]
            command = (
                ".\\prepare-hands-feet-nails-detail-candidate.ps1 "
                f"-Root {_quote(root)} -PersonId {_quote(person_id)} -BodyRevision {_quote(body_revision)} "
                f"-CaptureId {_quote(match['capture_id'])} -UvEvidence {_quote(match['uv_evidence_path'])} "
                f"-PackagePath {_quote(source_package_path)}"
            )
            actions[CANDIDATE_GATE] = {
                "gate": CANDIDATE_GATE,
                "command": command,
                "operator_input_required": False,
                "reason": "Reuse the one exact existing source-capture/landmark/UV authority chain and materialize its detail-bearing candidate.",
            }
            gates.append(_gate(
                CANDIDATE_GATE,
                "required",
                reason="one exact existing HFN source/UV authority chain can materialize the missing detail candidate",
                evidence={
                    "capture_id": match["capture_id"],
                    "uv_evidence_sha256": match["uv_evidence_sha256"],
                    "source_capture_sha256": match["source_capture_sha256"],
                    "landmark_evidence_sha256": match["landmark_evidence_sha256"],
                    "reuse_resolution": "unique-exact-existing-authority",
                },
            ))
            return {
                "gates": gates,
                "actions": actions,
                "package_path": source_package_path,
                "package_sha256": source_package_sha256,
                "reusable_detail_authority": dict(match),
            }
        command = (
            ".\\prepare-hands-feet-nails-detail-candidate.ps1 "
            f"-Root {_quote(root)} -PersonId {_quote(person_id)} -BodyRevision {_quote(body_revision)} "
            "-CaptureId <CAPTURE_ID> -UvEvidence <UV_EVIDENCE_PATH> "
            f"-PackagePath {_quote(source_package_path)}"
        )
        actions[CANDIDATE_GATE] = {
            "gate": CANDIDATE_GATE,
            "command": command,
            "operator_input_required": True,
            "reason": "Select the exact source-grounded HFN capture/UV evidence for this promoted package, then materialize its detail-bearing candidate.",
        }
        gates.append(_gate(CANDIDATE_GATE, "required", reason="no exact HFN detail candidate targets the face-secondary promoted package"))
        return {
            "gates": gates,
            "actions": actions,
            "package_path": source_package_path,
            "package_sha256": source_package_sha256,
            "reusable_detail_resolution": reusable,
        }
'''
text = text[:start] + new_block + text[end:]
CONTINUATION.write_text(text, encoding="utf-8", newline="\n")

text = EXECUTOR.read_text(encoding="utf-8")
start = text.index("    if gate == HFN_CANDIDATE_GATE:\n", text.index("if gate not in HFN_MACHINE_GATES"))
end = text.index("    else:\n        output = _need_absent(render_dir", start)
old = text[start:end]
new = r'''    if gate == HFN_CANDIDATE_GATE:
        candidate = status.get("candidate")
        if isinstance(candidate, Mapping):
            capture_id = _canonical_hfn_id(
                candidate.get("capture_id"), pattern=HFN_CAPTURE_RE, field="HFN capture_id"
            )
            candidate_id = _canonical_hfn_id(
                candidate.get("candidate_id"), pattern=HFN_CANDIDATE_RE, field="HFN candidate_id"
            )
            if candidate.get("fingernail_geometry_package_sha256"):
                script = "prepare-hands-feet-nails-toenail-geometry-candidate.ps1"
                substep = "toenail-geometry"
            else:
                script = "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1"
                substep = "fingernail-geometry"
            argv = _pwsh(
                repo_root,
                script,
                "-Root", str(hfn_root),
                "-PersonId", person_id,
                "-BodyRevision", body_revision,
                "-CaptureId", capture_id,
                "-CandidateId", candidate_id,
            )
        else:
            reusable = status.get("reusable_detail_authority")
            if not isinstance(reusable, Mapping):
                raise FidelityComponentGapExecutionError(
                    "machine-safe HFN candidate gate lacks exact detail-candidate or reusable source/UV authority"
                )
            if reusable.get("person_id") != person_id or reusable.get("body_revision") != body_revision:
                raise FidelityComponentGapExecutionError("reusable HFN detail authority belongs to a different Person/body")
            if reusable.get("body_id") != plan["body_id"] or reusable.get("source_package_sha256") != status_sha:
                raise FidelityComponentGapExecutionError("reusable HFN detail authority targets different body/package bytes")
            capture_id = _canonical_hfn_id(
                reusable.get("capture_id"), pattern=HFN_CAPTURE_RE, field="reusable HFN capture_id"
            )
            uv_evidence = _need_file(reusable.get("uv_evidence_path"), label="reusable HFN UV evidence")
            uv_sha = _canonical_sha(
                reusable.get("uv_evidence_sha256"), field="reusable HFN UV evidence SHA", length=64
            )
            if _sha256_file(uv_evidence) != uv_sha:
                raise FidelityComponentGapExecutionError("reusable HFN UV evidence bytes changed after continuation inspection")
            argv = _pwsh(
                repo_root,
                "prepare-hands-feet-nails-detail-candidate.ps1",
                "-Root", str(hfn_root),
                "-PersonId", person_id,
                "-BodyRevision", body_revision,
                "-CaptureId", capture_id,
                "-UvEvidence", str(uv_evidence),
                "-PackagePath", str(status_package),
            )
            substep = "detail-candidate"
'''
text = text[:start] + new + text[end:]
EXECUTOR.write_text(text, encoding="utf-8", newline="\n")

with CONT_TEST.open("a", encoding="utf-8", newline="\n") as handle:
    handle.write(r'''


def test_missing_candidate_reuses_one_exact_existing_source_uv_authority(tmp_path: Path, monkeypatch) -> None:
    source = _source_package(tmp_path)
    root = tmp_path / "people"
    capture = "hfncap-" + "7" * 32
    uv = tmp_path / "exact-uv.json"
    uv.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(subject, "resolve_reusable_detail_authority", lambda *args, **kwargs: {
        "state": "resolved",
        "matches": [{
            "person_id": PERSON,
            "body_revision": BODY,
            "body_id": "body-example",
            "capture_id": capture,
            "uv_evidence_path": str(uv.resolve()),
            "uv_evidence_sha256": hashlib.sha256(uv.read_bytes()).hexdigest(),
            "source_capture_sha256": "8" * 64,
            "landmark_evidence_sha256": "9" * 64,
            "source_package_sha256": SOURCE_SHA,
        }],
    })
    result = subject.inspect_hfn_continuation(
        root=root,
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=SOURCE_SHA,
        render_dir=tmp_path / "render",
        human_review_dir=tmp_path / "review",
    )
    action = result["actions"][subject.CANDIDATE_GATE]
    assert action["operator_input_required"] is False
    assert "<CAPTURE_ID>" not in action["command"]
    assert "<UV_EVIDENCE_PATH>" not in action["command"]
    assert capture in action["command"]
    assert str(uv.resolve()) in action["command"]
    assert result["reusable_detail_authority"]["capture_id"] == capture
    assert result["gates"][0]["evidence"]["reuse_resolution"] == "unique-exact-existing-authority"


def test_ambiguous_existing_source_uv_authority_keeps_operator_stop(tmp_path: Path, monkeypatch) -> None:
    source = _source_package(tmp_path)
    monkeypatch.setattr(subject, "resolve_reusable_detail_authority", lambda *args, **kwargs: {
        "state": "ambiguous",
        "matches": [{}, {}],
        "match_count": 2,
    })
    result = subject.inspect_hfn_continuation(
        root=tmp_path / "people",
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=SOURCE_SHA,
        render_dir=tmp_path / "render",
        human_review_dir=tmp_path / "review",
    )
    action = result["actions"][subject.CANDIDATE_GATE]
    assert action["operator_input_required"] is True
    assert "<CAPTURE_ID>" in action["command"]
    assert "<UV_EVIDENCE_PATH>" in action["command"]
    assert result["reusable_detail_resolution"]["state"] == "ambiguous"
''')

with EXEC_TEST.open("a", encoding="utf-8", newline="\n") as handle:
    handle.write(r'''


def test_hfn_one_exact_existing_source_uv_chain_makes_detail_candidate_machine_executable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context, package, _hfn_root = _hfn_context(tmp_path)
    capture = "hfncap-" + "7" * 32
    uv = tmp_path / "exact-uv.json"
    uv.write_text("exact uv\n", encoding="utf-8")
    uv_sha = hashlib.sha256(uv.read_bytes()).hexdigest()
    action = {
        "gate": executor.HFN_CANDIDATE_GATE,
        "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 exact",
        "operator_input_required": False,
        "reason": "reuse exact existing source UV authority",
    }
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: {
        "actions": {executor.HFN_CANDIDATE_GATE: action},
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
        "reusable_detail_authority": {
            "person_id": context["person_id"],
            "body_revision": context["body_revision"],
            "body_id": "body-example",
            "capture_id": capture,
            "uv_evidence_path": str(uv),
            "uv_evidence_sha256": uv_sha,
            "source_package_sha256": PACKAGE_SHA,
        },
    })
    result = executor.build_execution(
        plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
        context=context,
        repo_root=root,
    )
    assert result["mode"] == "machine-executable"
    assert result["hfn_substep"] == "detail-candidate"
    command = result["commands"][0]
    assert command[3] == str(root / "prepare-hands-feet-nails-detail-candidate.ps1")
    assert "-CaptureId" in command and capture in command
    assert "-UvEvidence" in command and str(uv.resolve()) in command
    assert "-PackagePath" in command and str(package.resolve()) in command
    assert result["reprobe_required_after_execution"] is True


def test_hfn_reusable_source_uv_authority_rejects_changed_uv_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = repo(tmp_path)
    context, package, _hfn_root = _hfn_context(tmp_path)
    uv = tmp_path / "exact-uv.json"
    uv.write_text("changed\n", encoding="utf-8")
    action = {
        "gate": executor.HFN_CANDIDATE_GATE,
        "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 exact",
        "operator_input_required": False,
        "reason": "reuse exact existing source UV authority",
    }
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: {
        "actions": {executor.HFN_CANDIDATE_GATE: action},
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
        "reusable_detail_authority": {
            "person_id": context["person_id"],
            "body_revision": context["body_revision"],
            "body_id": "body-example",
            "capture_id": "hfncap-" + "7" * 32,
            "uv_evidence_path": str(uv),
            "uv_evidence_sha256": "0" * 64,
            "source_package_sha256": PACKAGE_SHA,
        },
    })
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="UV evidence bytes changed"):
        executor.build_execution(
            plan("source-bound-hfn-continuation", missing=["fingernails", "toenails"]),
            context=context,
            repo_root=root,
        )
''')
