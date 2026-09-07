# BodyRig rig-window runbook

This runbook exists to maximize scarce time on the physical target rig. The rule is simple: **reuse the furthest valid evidence before spending GPU/WSL/Unity/Quest time on an earlier stage**.

The planner is read-only with respect to persistent BodyRig evidence. Historical Gate-A assessment executes the real Gate-A validator against temporary output and removes that output before returning. The planner never runs the mutating command it recommends.

## 0. Update before creating new evidence

From PowerShell 7+ on the target rig, before a new physical chain is frozen:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
.\update-windows.ps1 -NoBrowser
```

After a fresh Gate A or later physical acceptance evidence has been selected for continuation, do **not** pull, switch branches or edit tracked files until that exact chain is deliberately completed or abandoned.

## 1. Ask BodyRig for the cheapest valid continuation

```powershell
.\plan-rig-window.ps1
```

If the performer id and local BodyId alias are already known, provide them now so the fallback path is immediately source-bound:

```powershell
.\plan-rig-window.ps1 -PerformerId '<stash-performer-id>' -BodyId '<operator-alias>'
```

The planner uses this strict priority order.

### Priority 1 — historical Gate-A rescue

A failed body-build that already completed clone/recovery/fitting is assessed with the **real Gate-A validator** using temporary output. If it passes, the planner emits:

```powershell
.\resume-body-job.ps1 -JobId '<job-id>'
```

This path does **not** rerun clone, recovery or the SiTH fitter. The real resume builds the replacement Gate A in a sibling staging directory first; only after that full validation succeeds are old partial Gate-A/fidelity outputs preserved as quarantine evidence and the validated replacement promoted.

You can explicitly run the same source-preserving assessment yourself:

```powershell
.\resume-body-job.ps1 -JobId '<job-id>' -AssessOnly
```

`-AssessOnly` creates no persistent BodyRig evidence and does not run the Windows fidelity renderer.

### Priority 2 — existing Gate-A acceptance

If a valid Gate-A directory already exists, the planner asks the canonical physical acceptance status engine for its exact next command. Continue Windows/Quest/release from those bytes before considering another clone.

If that physical body acceptance chain is already complete, the planner stops and explicitly refuses to recommend fresh reconstruction for that body.

### Priority 3 — completed physical clone session

If there is no usable Gate-A continuation but a completed physical clone session exists on the exact current checkout revision, continue that session into Gate A instead of starting another reconstruction.

### Priority 4 — fresh profiled physical preflight

Only when no reusable Gate-A rescue, Gate-A continuation or exact-current completed clone session validates may the planner fall back to fresh profiled physical preflight/reconstruction.

With a performer/body pair supplied, the next command routes through checkout-bound `bodyrig-status.ps1`, which delegates to the canonical profiled first-run doctor. That doctor performs rig/source readiness and emits the exact production clone command; it still creates no physical session by itself.

## 2. Execute exactly one recommended next command

Run the command printed by the planner. Do not manually reconstruct a shorter command and do not skip directly to fresh SiTH merely because it is familiar.

After the command finishes, rerun:

```powershell
.\plan-rig-window.ps1
```

The planner should either advance to a later valid stage, report an already-complete body acceptance chain, or explain why reuse is no longer valid before permitting fresh reconstruction.

## 3. Human/physical evidence boundary

The planner and `-AssessOnly` can prove byte lineage, package validity, skin/topology structural QA, runtime materialization and checkout authority. They **cannot** create or infer:

- human visual/fidelity PASS;
- real Windows/Quest renderer PASS;
- new source observations;
- source-derived anatomy/hair/eyes/face review authority;
- full digital-twin M5/M6 activation.

Those gates still require the actual rig, real source bytes and explicit human review where the canonical contracts require them.
