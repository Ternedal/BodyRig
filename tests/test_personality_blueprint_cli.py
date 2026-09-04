from __future__ import annotations

import json
from pathlib import Path

from bodyrig import personality_blueprint_cli
from bodyrig.person_profiles import create_profile, load_profile
from bodyrig.personality_exemplar_approval import build_approval


def _style_report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["c" * 64],
        "candidate_count": 3,
        "candidates": [
            "Ja ja, det går nok.",
            "Nå, videre.",
            "Det var da typisk.",
        ],
        "suggested_exemplars": ["Ja ja, det går nok.", "Det var da typisk."],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def test_cli_builds_operator_grounded_candidate_without_body(capsys) -> None:
    rc = personality_blueprint_cli.main([
        "--default-language", "da",
        "--directness", "0.8",
        "--warmth", "0.7",
        "--verbosity", "0.2",
        "--authored-notes", "Tør, underspillet humor.",
        "--style-example", "Ja ja, det skal nok gå.",
        "--style-example", "Det er altså ikke verdens undergang.",
    ])

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "bodyrig-personality-blueprint-result"
    assert result["blueprint"]["grounding"] == {
        "communication": "operator-authored",
        "embodiment": "operator-authored",
        "body_revision": None,
    }
    assert result["blueprint"]["style_exemplars"] == [
        "Ja ja, det skal nok gå.",
        "Det er altså ikke verdens undergang.",
    ]
    assert result["style_evidence"] is None
    assert "Tør, underspillet humor." in result["candidate"]["instructions"]
    assert "style_exemplars=2" in result["candidate"]["style_notes"]
    assert len(result["audition_suite"]["probes"]) == 6
    assert result["audition_suite"]["human_review_required"] is True


def test_cli_consumes_only_approval_bound_transcript_examples(tmp_path: Path, capsys) -> None:
    report_value = _style_report()
    approval_value = build_approval(
        report_value,
        selected_candidate_indexes=[0, 2],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    report = tmp_path / "report.json"
    approval = tmp_path / "approval.json"
    report.write_text(json.dumps(report_value), encoding="utf-8")
    approval.write_text(json.dumps(approval_value), encoding="utf-8")

    rc = personality_blueprint_cli.main([
        "--style-report", str(report),
        "--style-approval", str(approval),
        "--directness", "0.8",
    ])

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["blueprint"]["style_exemplars"] == [
        "Ja ja, det går nok.",
        "Det var da typisk.",
    ]
    assert result["style_evidence"]["approved_count"] == 2
    assert len(result["style_evidence"]["candidate_report_sha256"]) == 64
    assert len(result["style_evidence"]["approval_sha256"]) == 64
    assert "style_report_sha256=" in result["candidate"]["style_notes"]
    assert "style_approval_sha256=" in result["candidate"]["style_notes"]


def test_cli_rejects_mismatched_style_report_and_approval(tmp_path: Path, capsys) -> None:
    report_value = _style_report()
    approval_value = build_approval(
        report_value,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    report_value["candidates"][0] = "En anden replik."
    report_value["suggested_exemplars"] = ["Det var da typisk."]
    report = tmp_path / "report.json"
    approval = tmp_path / "approval.json"
    report.write_text(json.dumps(report_value), encoding="utf-8")
    approval.write_text(json.dumps(approval_value), encoding="utf-8")

    rc = personality_blueprint_cli.main([
        "--style-report", str(report),
        "--style-approval", str(approval),
    ])

    assert rc == 1
    assert "exact candidate report" in capsys.readouterr().err


def test_cli_requires_style_report_and_approval_together(capsys) -> None:
    rc = personality_blueprint_cli.main(["--style-report", "report.json"])

    assert rc == 1
    assert "must be supplied together" in capsys.readouterr().err


def test_cli_requires_body_package_and_revision_together(capsys) -> None:
    rc = personality_blueprint_cli.main([
        "--body-revision", "body-r0001",
    ])

    assert rc == 1
    error = capsys.readouterr().err
    assert "body-package" in error
    assert "body-revision" in error


def test_cli_create_only_output_refuses_reuse(tmp_path: Path, capsys) -> None:
    output = tmp_path / "personality.json"
    args = ["--out", str(output), "--initiative", "0.75"]

    assert personality_blueprint_cli.main(args) == 0
    first = json.loads(output.read_text(encoding="utf-8"))
    assert first["candidate"]["default_language"] == "da"

    assert personality_blueprint_cli.main(args) == 1
    assert "already exists" in capsys.readouterr().err


def test_cli_rejects_invalid_language(capsys) -> None:
    rc = personality_blueprint_cli.main(["--default-language", "not a language"])

    assert rc == 1
    assert "default_language is invalid" in capsys.readouterr().err


def test_cli_can_save_compiled_candidate_into_existing_person_profile(
    tmp_path: Path, capsys
) -> None:
    library = tmp_path / "people"
    profile = create_profile(library, display_name="Test Person")
    output = tmp_path / "blueprints" / "personality-r0001.json"

    rc = personality_blueprint_cli.main([
        "--person-library", str(library),
        "--person-id", profile["person_id"],
        "--save-candidate",
        "--out", str(output),
        "--default-language", "en",
        "--directness", "0.85",
        "--warmth", "0.65",
        "--feedback", "First guided blueprint",
    ])

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["person_id"] == profile["person_id"]
    assert result["saved_personality_revision"] == "personality-r0001"

    saved = load_profile(library, profile["person_id"])
    revision = saved["personality_revisions"][0]
    assert revision["revision_id"] == "personality-r0001"
    assert revision["instructions"] == result["candidate"]["instructions"]
    assert revision["style_notes"] == result["candidate"]["style_notes"]
    assert revision["default_language"] == "en"
    assert revision["feedback"] == "First guided blueprint"

    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["saved_personality_revision"] == "personality-r0001"


def test_save_candidate_requires_create_only_blueprint_evidence(tmp_path: Path, capsys) -> None:
    library = tmp_path / "people"
    profile = create_profile(library, display_name="Test Person")

    rc = personality_blueprint_cli.main([
        "--person-library", str(library),
        "--person-id", profile["person_id"],
        "--save-candidate",
    ])

    assert rc == 1
    assert "requires --out" in capsys.readouterr().err
    assert load_profile(library, profile["person_id"])["personality_revisions"] == []
