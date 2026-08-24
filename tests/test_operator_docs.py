from __future__ import annotations

import re
from pathlib import Path


REFERENCE_RENDERER_ACCEPTANCE_CALL = re.compile(
    r"(?ms)^\.\\record-reference-renderer-acceptance\.ps1 `\n"
    r"(?P<args>(?:  -[^\n]+\n?)+)"
)
RECOVERY_PREFLIGHT_CALL = re.compile(
    r"(?ms)^bodyrig-recovery-preflight `\n"
    r"(?P<args>(?:  --[^\n]+\n?)+)"
)
VALIDATE_RIG_CALL = re.compile(
    r"(?ms)^\.\\validate-rig\.ps1 `\n"
    r"(?P<args>(?:  -[^\n]+\n?)+)"
)
COMPLETE_ACCEPTANCE_CALL = re.compile(
    r"(?ms)^\.\\complete-acceptance\.ps1 `\n"
    r"(?P<args>(?:  -[^\n]+\n?)+)"
)


def _calls(path: Path, pattern: re.Pattern[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [match.group("args") for match in pattern.finditer(text)]


def test_operator_docs_use_machine_authoritative_reference_renderer_attestation() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected_calls = {
        repo_root / "README.md": 2,
        repo_root / "docs" / "RIG_ACCEPTANCE.md": 2,
    }

    for path, expected_count in expected_calls.items():
        calls = _calls(path, REFERENCE_RENDERER_ACCEPTANCE_CALL)
        assert len(calls) == expected_count, (
            f"{path.relative_to(repo_root)} must document exactly {expected_count} "
            "record-reference-renderer-acceptance.ps1 invocations"
        )
        text = path.read_text(encoding="utf-8")
        assert ".\\record-renderer-acceptance.ps1 `" not in text, (
            f"{path.relative_to(repo_root)} must not expose the lower-level renderer "
            "identity fields in the canonical operator flow"
        )
        for args in calls:
            assert "-AcceptanceDir " in args
            assert "-Platform " in args
            assert "-QualityNote " in args
            assert "-RendererName " not in args
            assert "-RendererVersion " not in args


def test_recovery_preflight_docs_bind_to_pinned_phalp_checkout() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    paths = [repo_root / "README.md", repo_root / "docs" / "HMR2_BRIDGE.md"]
    for path in paths:
        calls = _calls(path, RECOVERY_PREFLIGHT_CALL)
        assert calls, f"{path.relative_to(repo_root)} must document bodyrig-recovery-preflight"
        for args in calls:
            assert "--phalp-repo " in args, (
                f"{path.relative_to(repo_root)} documents recovery preflight "
                "without the pinned --phalp-repo checkout"
            )


def test_low_level_validate_rig_docs_bind_to_pinned_phalp_checkout() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "docs" / "RIG_ACCEPTANCE.md"
    calls = _calls(path, VALIDATE_RIG_CALL)
    assert calls, "docs/RIG_ACCEPTANCE.md must document validate-rig.ps1"
    for args in calls:
        assert "-PhalpRepo " in args, (
            "docs/RIG_ACCEPTANCE.md documents validate-rig.ps1 without "
            "the mandatory -PhalpRepo checkout"
        )


def test_final_gate_docs_include_machine_and_deformation_probe_inputs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    paths = [repo_root / "README.md", repo_root / "docs" / "RIG_ACCEPTANCE.md"]
    for path in paths:
        calls = _calls(path, COMPLETE_ACCEPTANCE_CALL)
        assert len(calls) == 1, (
            f"{path.relative_to(repo_root)} must document exactly one "
            "complete-acceptance.ps1 invocation"
        )
        args = calls[0]
        for argument in (
            "-WindowsProbeReport ",
            "-WindowsDeformationReport ",
            "-QuestProbeReport ",
            "-QuestDeformationReport ",
        ):
            assert argument in args, (
                f"{path.relative_to(repo_root)} final gate omits {argument.strip()}"
            )
