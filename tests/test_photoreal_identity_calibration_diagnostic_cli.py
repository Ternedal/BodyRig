from __future__ import annotations

from pathlib import Path

import pytest

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
