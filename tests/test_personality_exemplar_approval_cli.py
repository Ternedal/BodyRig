from __future__ import annotations

import json
from pathlib import Path

from bodyrig import personality_exemplar_approval_cli


def _report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["b" * 64],
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


def test_cli_requires_both_explicit_confirmations(tmp_path: Path, capsys) -> None:
    report = tmp_path / "report.json"
    output = tmp_path / "approval.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")

    rc = personality_exemplar_approval_cli.main([
        str(report), "--index", "0", "--approve-style-use", "--out", str(output)
    ])
    assert rc == 1
    assert "speaker identity" in capsys.readouterr().err
    assert not output.exists()


def test_cli_creates_create_only_bound_approval(tmp_path: Path, capsys) -> None:
    report = tmp_path / "report.json"
    output = tmp_path / "approval.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    args = [
        str(report),
        "--index", "0",
        "--index", "2",
        "--confirm-speaker-identity",
        "--approve-style-use",
        "--out", str(output),
    ]

    assert personality_exemplar_approval_cli.main(args) == 0
    stdout = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert stdout == saved
    assert saved["selected_candidate_indexes"] == [0, 2]
    assert saved["approved_exemplars"] == [
        "Ja ja, det går nok.",
        "Det var da typisk.",
    ]
    assert saved["operator_review"] == {
        "speaker_identity_confirmed": True,
        "style_use_approved": True,
    }

    assert personality_exemplar_approval_cli.main(args) == 1
    assert "already exists" in capsys.readouterr().err
