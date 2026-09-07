# BodyRig rig-window runbook

This runbook exists to maximize scarce time on the physical target rig. The rule is simple: **reuse the furthest valid evidence before spending GPU/WSL/Unity/Quest time on an earlier stage**.

The planner is read-only with respect to persistent BodyRig evidence. Historical Gate-A assessment executes the real Gate-A validator against temporary output and removes that output before returning. Interrupted-recovery assessment delegates to the already-running BodyRig service and its existing exact-authority recovery planner. The planner never runs the mutating command it recommends.

## 0. Update before creating new evidence

From PowerShell 7+ on the target rig, before a new physical chain is frozen:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
.\update-windows.ps1 -NoBrowser
```

`update-windows.ps1` also starts/verifies the checkout-bound local BodyRig service, which lets the rig-window planner inspect existing interrupted-body recovery opportunities without duplicating service-owned Stash/Person authority.

After a fresh Gate A or later physical acceptance evidence has been selected for continuation, do **not** pull, switch branches or edit tracked files until that exact chain is deliberately completed or abandoned.

## 1. Ask BodyRig for the cheapest valid continuation

```powershell
.\plan-rig-window.ps1
```

If the performer id and local BodyId alias are already known, provide them now so the fallback path is immediately source-bound:

```powershell
.\plan-rig-window.ps1 -PerformerId '<stash-performer-id>' -BodyId '<operator-alias>'
```

If one specific historical UI job is the intended continuation, add `-PreferredJobId '<job-id>'`. This only changes candidate ordering; every candidate still has to pass its canonical validator.

The planner uses this strict reuse-first priority order.

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

### Priority 4 — interrupted package/reconstruction recovery

For other failed/interrupted body jobs on the exact current BodyRig revision, the planner asks the existing BodyRig service recovery engine whether retained private evidence can be reused. Two canonical modes already exist:

- **adopt complete package** — a complete source-bound package survived; expensive reconstruction **and fitter** do not rerun;
- **resume fit only** — completed SiTH reconstruction survived; expensive reconstruction does not rerun, but the fitter runs again from the retained exact reconstruction authority.

The planner first calls the read-only wrapper equivalent of:

```powershell
.\resume-interrupted-body-job.ps1 -JobId '<job-id>' -AssessOnly
```

Only an `available=true`, exact-current-revision plan with `expensive_reconstruction_rerun=false` can be recommended. The mutating command is then emitted, not executed automatically:

```powershell
.\resume-interrupted-body-job.ps1 -JobId '<job-id>'
```

That command delegates to BodyRig's existing `/resume-status` and `/resume` service endpoints, preserving their Person/Stash/source/workspace authority and active-job conflict checks.

### Priority 5 — fresh profiled physical preflight

Only when no reusable Gate-A rescue, Gate-A continuation, exact-current completed clone session, complete package or retained SiTH reconstruction validates may the planner fall back to fresh profiled physical preflight/reconstruction.

With a performer/body pair supplied, the next command routes through checkout-bound `bodyrig-status.ps1`, which delegates to the canonical profiled first-run doctor. That doctor performs rig/source readiness and emits the exact production clone command; it still creates no physical session by itself.

The crash-resilient recovery bridge will also reuse source-hash/adapter/revision-bound segment checkpoints within retained observation workspaces when the canonical recovery path reaches them. Do not manually copy checkpoint files between workspaces.

## 2. Execute exactly one recommended next command

Run the command printed by the planner. Do not manually reconstruct a shorter command and do not skip directly to fresh SiTH merely because it is familiar.

After the command finishes, rerun:

```powershell
.\plan-rig-window.ps1
```

The planner should either advance to a later valid stage, report an already-complete body acceptance chain, or explain why every reuse route is invalid before permitting fresh reconstruction.

## 3. Human/physical evidence boundary

The planner and assessment modes can prove byte lineage, package validity, skin/topology structural QA, runtime materialization, retained reconstruction/package authority and checkout authority. They **cannot** create or infer:

- human visual/fidelity PASS;
- real Windows/Quest renderer PASS;
- new source observations;
- source-derived anatomy/hair/eyes/face review authority;
- full digital-twin M5/M6 activation.

Those gates still require the actual rig, real source bytes and explicit human review where the canonical contracts require them.
