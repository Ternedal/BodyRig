from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_hand4whole_stage as stage


ROOT = Path(__file__).resolve().parents[1]
STAGE_OPERATOR = ROOT / "stage-photoreal-exavatar-hand4whole-assets.ps1"


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    source = root / "repos" / "ExAvatar_RELEASE" / "fitting" / "common" / "utils" / "human_model_files"
    hand4whole = root / "repos" / "Hand4Whole_RELEASE" / "common" / "utils"
    source.mkdir(parents=True)
    hand4whole.mkdir(parents=True)
    for relative in stage.REQUIRED_RELATIVE_FILES:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((relative + "\n").encode("utf-8"))
    receipt: dict[str, object] = {
        "format": stage.WORKSPACE_FORMAT,
        "version": stage.VERSION,
        "smplx_gender": "female",
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["workspace_sha256"] = _digest(receipt, "workspace_sha256")
    (root / "workspace-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return root


def test_hand4whole_stage_links_complete_human_model_tree_and_writes_receipt(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = stage.stage_hand4whole_assets(workspace_root=root)

    target = root / result["target_tree_relative_path"]
    assert target.is_symlink()
    assert result["smplx_gender"] == "female"
    assert result["required_asset_count"] == len(stage.REQUIRED_RELATIVE_FILES)
    assert result["held_out_evaluation_disclosed"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    validated = stage.validate_hand4whole_assets_receipt(workspace_root=root)
    assert validated["hand4whole_assets_sha256"] == result["hand4whole_assets_sha256"]


def test_hand4whole_stage_blocks_missing_required_asset(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    missing = root / "repos" / "ExAvatar_RELEASE" / "fitting" / "common" / "utils" / "human_model_files" / "smplx" / "SMPLX_to_J14.pkl"
    missing.unlink()

    with pytest.raises(stage.PhotorealExAvatarHand4WholeStageError, match="required Hand4Whole human-model asset missing"):
        stage.stage_hand4whole_assets(workspace_root=root)


def test_hand4whole_receipt_detects_asset_mutation_after_staging(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stage.stage_hand4whole_assets(workspace_root=root)
    target = root / "repos" / "Hand4Whole_RELEASE" / "common" / "utils" / "human_model_files"
    (target / "smpl" / "SMPL_NEUTRAL.pkl").write_bytes(b"mutated")

    with pytest.raises(stage.PhotorealExAvatarHand4WholeStageError, match="staged asset (size|SHA) mismatch"):
        stage.validate_hand4whole_assets_receipt(workspace_root=root)


def test_hand4whole_stage_refuses_existing_destination(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    target = root / "repos" / "Hand4Whole_RELEASE" / "common" / "utils" / "human_model_files"
    target.mkdir()

    with pytest.raises(stage.PhotorealExAvatarHand4WholeStageError, match="destination already exists"):
        stage.stage_hand4whole_assets(workspace_root=root)



def test_hand4whole_stage_operator_wsl_path_stdout_is_codepage_independent() -> None:
    text = STAGE_OPERATOR.read_text(encoding="utf-8")

    assert "import base64" in text
    assert 'base64.b64encode(value.encode("utf-8")).decode("ascii")' in text
    assert "[Convert]::FromBase64String($encodedRepo)" in text
    assert "[Text.Encoding]::UTF8.GetString" in text
    assert "print(make_wsl_path_converter" not in text
