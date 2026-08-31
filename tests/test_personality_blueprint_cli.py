from __future__ import annotations

import json
from pathlib import Path

from bodyrig import personality_blueprint_cli
from bodyrig.person_profiles import create_profile, load_profile


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
    assert "Tør, underspillet humor." in result["candidate"]["instructions"]
    assert "style_exemplars=2" in result["candidate"]["style_notes"]
    assert len(result["audition_suite"]["probes"]) == 6
    assert result["audition_suite"]["human_review_required"] is True


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
