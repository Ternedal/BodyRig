from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import pytest

from bodyrig import photoreal_identity_calibration_diagnostic_cli as cli
from bodyrig.photoreal_identity_calibration_diagnostic_cli import (
    _parser,
    _resolve_paths,
)


def test_run_root_resolves_canonical_resume_artifacts(
    tmp_path: Path,
) -> None:
    parser = _parser()
    args = parser.parse_args(
        [
            "--run-root",
            str(tmp_path),
        ]
    )

    bank, plan, negatives, output = _resolve_paths(args, parser)

    root = tmp_path.resolve()
    assert bank == root / "identity-bank.json"
    assert plan == root / "identity-calibration-plan.json"
    assert negatives == (
        root
        / "identity-calibration-extractor"
        / "output"
        / "negative-observations.json"
    )
    assert output == root / "identity-calibration-diagnostic.json"


def test_run_root_allows_explicit_output_override(
    tmp_path: Path,
) -> None:
    parser = _parser()
    output = tmp_path / "custom.json"
    args = parser.parse_args(
        [
            "--run-root",
            str(tmp_path),
            "--out",
            str(output),
        ]
    )

    *_, resolved_output = _resolve_paths(args, parser)

    assert resolved_output == output


def test_explicit_mode_preserves_resume_hook_contract(
    tmp_path: Path,
) -> None:
    bank = tmp_path / "bank.json"
    plan = tmp_path / "plan.json"
    negatives = tmp_path / "negatives.json"
    output = tmp_path / "diagnostic.json"

    parser = _parser()
    args = parser.parse_args(
        [
            "--identity-bank",
            str(bank),
            "--plan",
            str(plan),
            "--negative-observations",
            str(negatives),
            "--out",
            str(output),
        ]
    )

    assert _resolve_paths(args, parser) == (
        bank,
        plan,
        negatives,
        output,
    )


def test_run_root_rejects_mixed_explicit_inputs(
    tmp_path: Path,
) -> None:
    parser = _parser()
    args = parser.parse_args(
        [
            "--run-root",
            str(tmp_path),
            "--identity-bank",
            str(tmp_path / "bank.json"),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        _resolve_paths(args, parser)

    assert exc.value.code == 2


def test_explicit_mode_rejects_partial_paths(
    tmp_path: Path,
) -> None:
    parser = _parser()
    args = parser.parse_args(
        [
            "--identity-bank",
            str(tmp_path / "bank.json"),
        ]
    )

    with pytest.raises(SystemExit) as exc:
        _resolve_paths(args, parser)

    assert exc.value.code == 2


def test_cli_summary_exposes_stage13_separation_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = defaultdict(
        lambda: 0,
        {
            "format": "bodyrig-photoreal-identity-calibration-diagnostic",
            "version": 1,
            "target_performer_id": "42",
            "observed_separation_margin": -0.125,
            "minimum_required_separation_margin": 0.05,
            "maximum_allowed_negative_cosine": 0.7,
            "stage13_calibration_blockers": [
                "positive/negative identity separation is insufficient"
            ],
            "negative_observation_quality_metadata": {
                "expected_fields": ["face_visibility", "sharpness"],
                "observed_fields": [],
                "missing_fields": ["face_visibility", "sharpness"],
                "field_presence_counts": {
                    "face_visibility": 0,
                    "sharpness": 0,
                },
                "complete_observation_count": 0,
                "complete_observation_fraction": 0.0,
                "complete_quality_audit_available": False,
                "reextraction_required_for_complete_quality_audit": True,
            },
            "violating_closest_positive_group_summaries": [
                {
                    "group_id": "a",
                    "observation_count": 1,
                    "observation_fraction": 1.0,
                }
            ],
            "highest_negative_match": {
                "subject_performer_id": "7",
                "resolved_path": r"C:\negative\p7.mp4",
            },
            "highest_collision_negative_source": {
                "source_key": "n7",
                "resolved_path": r"C:\negative\p7.mp4",
            },
        },
    )

    monkeypatch.setattr(
        cli,
        "build_identity_calibration_diagnostic_files",
        lambda *args, **kwargs: result,
    )

    exit_code = cli.main(["--run-root", str(tmp_path)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["observed_separation_margin"] == -0.125
    assert payload["minimum_required_separation_margin"] == 0.05
    assert payload["maximum_allowed_negative_cosine"] == 0.7
    assert payload["stage13_calibration_blockers"] == [
        "positive/negative identity separation is insufficient"
    ]
    assert payload[
        "negative_observation_quality_metadata"
    ]["reextraction_required_for_complete_quality_audit"] is True
    assert payload[
        "negative_observation_quality_metadata"
    ]["complete_quality_audit_available"] is False
    assert payload[
        "violating_closest_positive_group_summaries"
    ] == [
        {
            "group_id": "a",
            "observation_count": 1,
            "observation_fraction": 1.0,
        }
    ]



def test_console_json_is_ascii_safe_for_legacy_windows_codepages() -> None:
    payload = {
        "performer_name": "Łukasz – 測試 😀",
        "path": r"C:\VR\scene.mp4",
    }

    rendered = cli._console_json(payload)

    rendered.encode("cp1252")
    decoded = json.loads(rendered)
    assert decoded == payload
    assert "\\u" in rendered
