from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "probe-photoreal-scout-latest.ps1").read_text(encoding="utf-8")


def test_latest_replay_defaults_to_bodyrig_overnight_root() -> None:
    assert '$env:LOCALAPPDATA' in SCRIPT
    assert 'BodyRig\\photoreal-v2\\overnight' in SCRIPT
    assert 'LOCALAPPDATA is required when SearchRoot is not supplied.' in SCRIPT
    assert 'Photoreal overnight search root not found:' in SCRIPT


def test_latest_replay_selects_newest_valid_authority_triplet() -> None:
    assert 'Get-ChildItem -LiteralPath $SearchRoot -Recurse -Filter "source-receipt.json" -File' in SCRIPT
    assert 'Sort-Object LastWriteTimeUtc -Descending' in SCRIPT
    assert 'Test-AuthorityTriplet -CandidateRoot $candidate -ReceiptPath $receipt.FullName' in SCRIPT
    assert 'bodyrig-photoreal-source-inventory' in SCRIPT
    assert 'bodyrig-photoreal-dataset-plan' in SCRIPT
    assert 'bodyrig-photoreal-source-receipt' in SCRIPT
    assert 'source-inventory.json' in SCRIPT
    assert 'dataset-plan.json' in SCRIPT
    assert 'No replayable Photoreal P0 root with a valid source-inventory.json, dataset-plan.json and source-receipt.json authority triplet' in SCRIPT
    assert 'Selection policy:  latest valid authority triplet' in SCRIPT


def test_latest_replay_rejects_malformed_or_crossed_authority_candidates() -> None:
    assert 'function Read-JsonObjectOrNull' in SCRIPT
    assert 'function Test-HasFields' in SCRIPT
    assert 'function Test-StrictBoolean' in SCRIPT
    assert 'function Test-StrictInteger' in SCRIPT
    assert '$Value.PSObject.Properties.Name' in SCRIPT
    assert 'all_sources_readable' in SCRIPT
    assert 'all_sources_sha256_bound' in SCRIPT
    assert 'source_keys_path_specific' in SCRIPT
    assert 'teacher_training_authorized' in SCRIPT
    assert SCRIPT.count('production_activation') >= 3
    assert 'ConvertFrom-Json -Depth' not in SCRIPT
    assert '[int]$inventory.version' not in SCRIPT
    assert '[int]$plan.version' not in SCRIPT
    assert '[int]$receipt.version' not in SCRIPT
    assert 'Test-StrictInteger -Value $inventory.version -Expected 1' in SCRIPT
    assert 'Test-StrictInteger -Value $plan.version -Expected 1' in SCRIPT
    assert 'Test-StrictInteger -Value $receipt.version -Expected 1' in SCRIPT


def test_latest_replay_delegates_to_hardened_read_only_replay() -> None:
    assert 'probe-photoreal-scout-authority.ps1' in SCRIPT
    assert '$replayArgs = @{' in SCRIPT
    assert 'OutputRoot = $selectedRoot' in SCRIPT
    assert '$replayArgs["ProbeRoot"] = $ProbeRoot' in SCRIPT
    assert '$replayArgs["BodyRigPython"] = $BodyRigPython' in SCRIPT
    assert '& $replay @replayArgs' in SCRIPT
    assert 'Mutation:          FALSE' in SCRIPT