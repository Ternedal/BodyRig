# BodyRig rig-window runbook

This runbook exists to maximize scarce time on the physical target rig. The rule is simple: **reuse the furthest valid evidence before spending GPU/WSL/Unity/Quest time on an earlier stage**.

`plan-rig-window.ps1` is intentionally a thin checkout-bound PowerShell wrapper. It proves clean Git authority and checkout-bound Python imports, then delegates read-only planning to `bodyrig.rig_window_plan`. This keeps the Windows operator surface stable while making evidence ranking and fallback behavior directly unit-testable.

The planner is read-only with respect to persistent BodyRig evidence. Historical Gate-A assessment executes the real Gate-A validator against temporary output and removes that output before returning. Interrupted-recovery assessment delegates to the already-running BodyRig service and its existing exact-authority recovery planner. The planner never runs the mutating command it recommends.

## 0. Update before creating new evidence

From PowerShell 7+ on the target rig, before a new physical chain is frozen:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
.\update-windows.ps1 -NoBrowser
```

`update-windows.ps1` also starts/verifies the checkout-bound local BodyRig service, which lets the rig-window planner inspect existing interrupted-body recovery opportunities without duplicating service-owned Stash/Person authority.

For an already-valid historical acceptance, the same updater can re-enter its exact accepted revision safely:

```powershell
.\update-windows.ps1 -Revision '<40-char-sha>' -NoBrowser
```

Historical mode is fail-closed. The requested SHA must be a Git commit reachable as an ancestor of the freshly fetched `origin/main`, and that exact commit must contain its own Windows runtime lock, runtime-lock validator, launcher and acceptance-status tooling before the currently running BodyRig service is stopped. The target revision is then checked out detached, its own Windows dependency lock is installed and verified, and the restarted service must report that exact revision.

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

### Priority 2 — furthest existing physical acceptance

All structurally valid Gate-A acceptance directories are inspected before one is selected. Selection is by physical progress first and timestamp only as a tie-breaker:

`release > quest-attestation > quest-probe > windows-attestation > windows-probe > gate-a`

A newer early-stage acceptance therefore cannot displace an older acceptance that has already consumed more scarce Windows/Quest/human-review work. Structural ranking deliberately uses the evidence chain's own revision-bound bytes and does not apply today's renderer policy to downgrade historical evidence. Current operator/reference policy is applied only after the selected evidence revision is active.

If the selected acceptance belongs to the current revision, the canonical physical acceptance status engine emits its exact next command. If it belongs to an older BodyRig revision, revision mismatch is **not** treated as a reason to reconstruct. The planner emits a guarded historical checkout command using `update-windows.ps1 -Revision <accepted-sha>`, then invokes that accepted revision's own `physical-acceptance-status.ps1`. The updater independently verifies that the requested SHA is a safe ancestor of current `origin/main` before stopping the service.

If the furthest physical body acceptance chain is already complete, the planner stops and explicitly refuses to recommend fresh reconstruction for that body.

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

Only when no reusable Gate-A rescue, downstream acceptance, completed physical session, complete package or retained SiTH reconstruction validates may the planner fall back to fresh profiled physical preflight/reconstruction.

With a performer/body pair supplied, the next command routes through checkout-bound `bodyrig-status.ps1`, which delegates to the canonical profiled first-run doctor. That doctor performs rig/source readiness and emits the exact production clone command; it still creates no physical session by itself.

The crash-resilient recovery bridge will also reuse source-hash/adapter/revision-bound segment checkpoints within retained observation workspaces when the canonical recovery path reaches them. Do not manually copy checkpoint files between workspaces.

## 2. Execute exactly one recommended next command

Run the command printed by the planner. Do not manually reconstruct a shorter command and do not skip directly to fresh SiTH merely because it is familiar.

After a normal current-revision command finishes, rerun:

```powershell
.\plan-rig-window.ps1
```

If the planner deliberately switches to an older accepted revision, follow the `physical-acceptance-status.ps1` command printed immediately after that switch instead. Older accepted revisions may predate `plan-rig-window.ps1`; that is expected and is why the historical-switch command chains directly into the accepted revision's canonical status engine.

The flow should either advance to a later valid stage, report an already-complete body acceptance chain, or explain why every reuse route is invalid before permitting fresh reconstruction.

## 3. Human/physical evidence boundary

The planner and assessment modes can prove byte lineage, package validity, skin/topology structural QA, runtime materialization, retained reconstruction/package authority and checkout authority. They **cannot** create or infer:

- human visual/fidelity PASS;
- real Windows/Quest renderer PASS;
- new source observations;
- source-derived anatomy/hair/eyes/face review authority;
- full digital-twin M5/M6 activation.

Those gates still require the actual rig, real source bytes and explicit human review where the canonical contracts require them.
