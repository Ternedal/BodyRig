from __future__ import annotations

import json
from pathlib import Path

from bodyrig import personality_blueprint_cli


def test_cli_builds_operator_grounded_candidate_without_body(capsys) -> None:
    rc = personality_blueprint_cli.main([
        "--default-language", "da",
        "--directness", "0.8",
        "--warmth", "0.7",
        "--verbosity", "0.2",
        "--authored-notes", "Tør, underspillet humor.",
    ])

    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "bodyrig-personality-blueprint-result"
    assert result["blueprint"]["grounding"] == {
        "communication": "operator-authored",
        "embodiment": "operator-authored",
        "body_revision": None,
    }
    assert "Tør, underspillet humor." in result["candidate"]["instructions"]


def test_cli_requires_body_package_and_revision_together(capsys) -> None:
    rc = personality_blueprint_cli.main([
        "--body-revision", "body-r0001",
    ])

    assert rc == 1
    assert "must be supplied together" in capsys.readouterr().err


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
