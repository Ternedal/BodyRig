from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


# Current handoff: remove active-candidate/operator routing that contradicts retirement.
p = Path("HANDOFF.md")
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    "`start-ab-baseline.ps1` is the canonical wrapper when the active #258 PBR-v3 and #208 throughput-v3 candidates are both receiving fresh physical comparison evidence",
    "`start-ab-baseline.ps1` is the archived v1 comparison launcher; #258 PBR-v3 and #208 throughput-v3 were reviewed/promoted on 2026-09-10, so it is not an active new-work entrypoint and now requires a new versioned candidate contract/lifecycle before any future A/B baseline",
    "HANDOFF operator-hardening bullet",
)
s, n = re.subn(
    r"- \*\*#258 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE:\*\*[^\n]*",
    "- **#258 — PROMOTED/HISTORICAL PBR-V3 CANDIDATE:** reviewed PBR-v3 source lineage. It is preserved for historical evidence only and is not current new-work candidate authority.",
    s,
    count=1,
)
if n != 1:
    raise SystemExit("missing #258 active classification")
s, n = re.subn(
    r"- \*\*#208 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE:\*\*[^\n]*",
    "- **#208 — PROMOTED/HISTORICAL THROUGHPUT-V3 CANDIDATE:** reviewed throughput-v3 lineage. It is preserved for historical evidence only and is not current new-work candidate authority.",
    s,
    count=1,
)
if n != 1:
    raise SystemExit("missing #208 active classification")
start = "When the active #258 PBR-v3 and #208 throughput-v3 candidates are both going to receive **fresh physical comparison evidence**"
end = "As evidence is created, continue through the same router with the relevant selector:"
if start not in s or end not in s:
    raise SystemExit("HANDOFF active A/B operator block anchors missing")
a = s.index(start)
b = s.index(end, a)
replacement = (
    "The 2026-09-10 #258/#208 shared A/B v1 cycle is **completed, promoted and archived**. "
    "`start-ab-baseline.ps1`, its PBR continuation and the throughput plan-bound continuation are historical-v1 tooling, not current new-work operator routing. "
    "Current `main` deliberately fails closed before new A/B physical work because `contracts/ab-baseline-cycle-state-v1.json` records `completed-promoted`. "
    "Do not create another baseline against the v1 contract. Any future candidate comparison must introduce a new versioned candidate contract/lifecycle first. "
    "Historical procedure remains documented in `docs/AB_BASELINE.md` for evidence interpretation only.\n\n"
)
s = s[:a] + replacement + s[b:]
p.write_text(s, encoding="utf-8", newline="\n")

# First physical run guide: archive the alternate A/B mode and route new work through standalone clone/acceptance.
p = Path("docs/FIRST_PHYSICAL_RUN.md")
s = p.read_text(encoding="utf-8")
pattern = r"### Dual-candidate A/B baseline\n.*?(?=\n## 0\. Start from the verified operator checkout)"
replacement = """### Archived dual-candidate A/B v1

The 2026-09-10 PBR-v3 / recovery-throughput-v3 shared candidate cycle is complete and promoted. **Do not use `start-ab-baseline.ps1` for a new physical run.** Current `main` intentionally blocks that launcher through the completed v1 lifecycle state.

For new physical/high-fidelity evidence, continue with the standalone first clone / acceptance route below. If a future software candidate genuinely needs A/B comparison, create and review a new versioned candidate contract/lifecycle before adding a new comparison launcher path. The completed v1 commands remain only in `docs/AB_BASELINE.md` as historical evidence documentation.
"""
s, n = re.subn(pattern, replacement, s, count=1, flags=re.S)
if n != 1:
    raise SystemExit("FIRST_PHYSICAL_RUN A/B section anchor missing")
p.write_text(s, encoding="utf-8", newline="\n")

# Historical A/B runbook: retain procedure but make non-current status impossible to miss.
p = Path("docs/AB_BASELINE.md")
s = p.read_text(encoding="utf-8")
old = """# Shared physical A/B baseline

`start-ab-baseline.ps1` is the canonical operator entrypoint when the active PBR-v3 and recovery-throughput-v3 draft candidates are both going to receive fresh physical comparison evidence.

It exists to avoid paying for two identical expensive current-main baseline reconstructions while preserving exact revision and candidate-byte authority.

The active PBR comparison candidate is the linear-light v3 replacement in PR #258. PR #196 is superseded historical PBR-v2 lineage and is not current shared-baseline authority.
"""
new = """# Historical shared physical A/B baseline v1

This document records the completed 2026-09-10 PBR-v3 / recovery-throughput-v3 evidence procedure. It is retained so the existing plan, review and promotion receipts remain interpretable.

**Do not execute this v1 procedure to create new evidence on current `main`.** `start-ab-baseline.ps1` now fails closed because the v1 lifecycle is `completed-promoted`. A future A/B cycle requires a new versioned candidate contract/lifecycle and fresh operator routing; it must not mutate or reactivate this historical authority.

PR #258 is promoted historical PBR-v3 lineage. PR #196 remains superseded PBR-v2 lineage.
"""
s = replace_once(s, old, new, "AB_BASELINE intro")
p.write_text(s, encoding="utf-8", newline="\n")

# Candidate-specific review docs: historical after promotion, not active launch instructions.
p = Path("docs/PBR_AB_PHYSICAL_REVIEW.md")
s = p.read_text(encoding="utf-8")
s = replace_once(s, "# PBR v3 physical A/B review", "# Historical PBR v3 physical A/B review", "PBR title")
s = replace_once(
    s,
    "This runbook prepares a revision-bound visual comparison for the current source-derived skin PBR v3 candidate without granting physical, renderer, release, or production authority.",
    "This runbook records the revision-bound visual comparison used for the now-promoted source-derived skin PBR v3 candidate. It is historical evidence documentation and does not authorize a new v1 comparison run.",
    "PBR intro",
)
s = replace_once(
    s,
    "The active candidate is PR #258; PR #196 remains historical/superseded lineage and is not current shared-baseline authority.",
    "PR #258 is promoted historical PBR-v3 lineage; PR #196 remains historical/superseded PBR-v2 lineage. Neither is current shared-baseline candidate authority.",
    "PBR candidate classification",
)
s = replace_once(s, "## Canonical shared-baseline path", "## Historical shared-baseline path — completed v1", "PBR path heading")
p.write_text(s, encoding="utf-8", newline="\n")

p = Path("docs/THROUGHPUT_PLAN_BOUND_REVIEW.md")
s = p.read_text(encoding="utf-8")
s = replace_once(s, "# Plan-bound recovery throughput A/B continuation", "# Historical plan-bound recovery throughput A/B continuation", "throughput title")
s = replace_once(
    s,
    "This flow is for the physical throughput candidate created by the canonical `start-throughput-candidate-from-ab-plan.ps1` sequencing gate.",
    "This flow records the completed v1 physical throughput-candidate continuation. It is historical evidence documentation; `start-throughput-candidate-from-ab-plan.ps1` is not a current new-work entrypoint after promotion.",
    "throughput intro",
)
p.write_text(s, encoding="utf-8", newline="\n")

# Tests now enforce retirement rather than former active-candidate routing.
Path("tests/test_ab_baseline_handoff_routing.py").write_text(
    '''from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
AB_DOC = (ROOT / "docs" / "AB_BASELINE.md").read_text(encoding="utf-8")


def test_handoff_routes_new_work_away_from_completed_ab_v1() -> None:
    assert "completed, promoted and archived" in HANDOFF
    assert "not current new-work operator routing" in HANDOFF
    assert "new versioned candidate contract/lifecycle" in HANDOFF
    assert "Historical shared physical A/B baseline v1" in AB_DOC
    assert "Do not execute this v1 procedure" in AB_DOC


def test_handoff_classifies_reviewed_candidates_as_promoted_historical() -> None:
    assert "#258 — PROMOTED/HISTORICAL PBR-V3 CANDIDATE" in HANDOFF
    assert "#208 — PROMOTED/HISTORICAL THROUGHPUT-V3 CANDIDATE" in HANDOFF
    assert "#258 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE" not in HANDOFF
    assert "#208 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE" not in HANDOFF
    assert "#196 — SUPERSEDED PBR-V2 CANDIDATE" in HANDOFF


def test_handoff_keeps_generic_revision_bound_launcher_for_new_non_ab_builds() -> None:
    assert "start-revision-bound-body-build.ps1" in HANDOFF
    assert "ordinary standalone fresh `body-build`" in HANDOFF
    assert "Any future candidate comparison must introduce a new versioned candidate contract/lifecycle first" in HANDOFF


def test_historical_ab_docs_preserve_evidence_interpretation_without_reactivation() -> None:
    assert "start-ab-baseline.ps1" in AB_DOC
    assert "completed-promoted" in AB_DOC
    assert "historical evidence" in AB_DOC.lower()
    assert "must not mutate or reactivate this historical authority" in AB_DOC
''',
    encoding="utf-8",
    newline="\n",
)

p = Path("tests/test_first_physical_run_docs.py")
s = p.read_text(encoding="utf-8")
pattern = r"def test_first_physical_run_splits_standalone_and_dual_candidate_modes_before_clone\(\) -> None:\n.*?(?=\n\ndef test_first_physical_run_requires_sith_v4)"
replacement = '''def test_first_physical_run_routes_new_work_away_from_archived_ab_v1() -> None:
    text = (ROOT / "docs" / "FIRST_PHYSICAL_RUN.md").read_text(encoding="utf-8")

    assert "Standalone first clone / acceptance" in text
    assert "Archived dual-candidate A/B v1" in text
    assert "Do not use `start-ab-baseline.ps1` for a new physical run" in text
    assert "continue with the standalone first clone / acceptance route below" in text
    assert "new versioned candidate contract/lifecycle" in text
    assert '.\\start-ab-baseline.ps1 -PerformerId "123"' not in text
    assert text.index("Archived dual-candidate A/B v1") < text.index("## 4. Choose a local operator alias")
'''
s, n = re.subn(pattern, replacement, s, count=1, flags=re.S)
if n != 1:
    raise SystemExit("first physical docs test anchor missing")
p.write_text(s, encoding="utf-8", newline="\n")

# Self-cleanup: these files must not enter the permanent PR diff.
Path(".github/workflows/_close_retired_ab_routing_v2.yml").unlink()
Path("tools/_close_retired_ab_routing.py").unlink()
