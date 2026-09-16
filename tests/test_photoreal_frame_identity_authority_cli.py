from __future__ import annotations

import json
from pathlib import Path

from bodyrig import photoreal_frame_identity_authority_cli as cli
from bodyrig.photoreal_frame_identity_authority import PhotorealFrameIdentityAuthorityError


def _result() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-frame-authorized-observations",
        "version": 1,
        "performer_id": "42",
        "identity_matching_calibrated": True,
        "identity_match_threshold": 0.82,
        "identity_ambiguous_sample_count": 1,
        "observations": [
            {"target_identity_verified": True},
            {"target_identity_verified": False},
        ],
        "identity_authority_is_core_derived": True,
        "multi_candidate_identity_safe": True,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def test_cli_wires_all_authority_inputs(monkeypatch, tmp_path: Path, capsys) -> None:
    captured: dict[str, Path] = {}

    def fake_authorize(plan, measurements, bank, calibration, output):
        captured.update(
            {
                "plan": plan,
                "measurements": measurements,
                "bank": bank,
                "calibration": calibration,
                "output": output,
            }
        )
        return _result()

    monkeypatch.setattr(cli, "authorize_frame_identity_files_sealed_strict", fake_authorize)
    paths = {name: tmp_path / f"{name}.json" for name in ("plan", "measurements", "bank", "calibration", "out")}

    code = cli.main(
        [
            "--plan", str(paths["plan"]),
            "--measurements", str(paths["measurements"]),
            "--identity-bank", str(paths["bank"]),
            "--identity-calibration", str(paths["calibration"]),
            "--out", str(paths["out"]),
        ]
    )

    assert code == 0
    assert captured == paths
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "bodyrig-photoreal-frame-authorized-observations"
    assert payload["target_identity_verified_count"] == 1
    assert payload["identity_unresolved_count"] == 1
    assert payload["identity_ambiguous_sample_count"] == 1
    assert payload["identity_authority_is_core_derived"] is True
    assert payload["multi_candidate_identity_safe"] is True
    assert payload["photoreal_acceptance_authority"] is False
    assert payload["production_activation"] is False


def test_cli_fails_closed_on_authority_error(monkeypatch, tmp_path: Path, capsys) -> None:
    def fail(*_args, **_kwargs):
        raise PhotorealFrameIdentityAuthorityError("calibration mismatch")

    monkeypatch.setattr(cli, "authorize_frame_identity_files_sealed_strict", fail)
    path = tmp_path / "x.json"
    code = cli.main(
        [
            "--plan", str(path),
            "--measurements", str(path),
            "--identity-bank", str(path),
            "--identity-calibration", str(path),
            "--out", str(path),
        ]
    )

    assert code == 1
    assert "calibration mismatch" in capsys.readouterr().err
