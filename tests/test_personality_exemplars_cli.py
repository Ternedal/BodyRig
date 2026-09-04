from __future__ import annotations

import json
from pathlib import Path

from bodyrig import personality_exemplars_cli


def test_cli_writes_create_only_review_report(tmp_path: Path, capsys) -> None:
    source = tmp_path / "clip.srt"
    output = tmp_path / "review.json"
    source.write_text(
        """1
00:00:01,000 --> 00:00:02,000
Ja ja, det går nok.

2
00:00:03,000 --> 00:00:04,000
Nå, videre.
""",
        encoding="utf-8",
    )

    rc = personality_exemplars_cli.main([
        str(source),
        "--suggested-limit", "1",
        "--out", str(output),
    ])

    assert rc == 0
    stdout = json.loads(capsys.readouterr().out)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert stdout == saved
    assert saved["candidate_count"] == 2
    assert len(saved["suggested_exemplars"]) == 1
    assert saved["operator_review_required"] is True
    assert saved["speaker_identity_authority"] is False

    rc = personality_exemplars_cli.main([
        str(source),
        "--out", str(output),
    ])
    assert rc == 1
    assert "already exists" in capsys.readouterr().err
