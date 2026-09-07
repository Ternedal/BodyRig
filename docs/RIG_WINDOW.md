# BodyRig rig-window runbook

This runbook exists to maximize scarce time on the physical target rig. The rule is simple: **reuse the furthest valid evidence before spending GPU/WSL/Unity/Quest time on an earlier stage**.

`plan-rig-window.ps1` is intentionally a thin checkout-bound PowerShell wrapper. It proves clean Git authority and checkout-bound Python imports, then delegates read-only selection to `bodyrig.rig_window_authority_policy`. That authority layer guards the unified ranking engine in `bodyrig.rig_window_policy`, which reuses validation/discovery primitives from `bodyrig.rig_window_plan`. This keeps the Windows operator surface stable while making evidence ordering, Person scoping, repository-lineage authority and fallback behavior directly unit-testable.

The planner is read-only with respect to persistent BodyRig evidence. Historical Gate-A assessment executes the real Gate-A validator against temporary output and removes that output before returning. Interrupted-recovery assessment delegates to the already-running BodyRig service and its existing exact-authority recovery planner. The planner never runs the mutating command it recommends.

## 0. Update and get the next rig action in one command

From the target rig, normal current-`main` startup is:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
.\update-windows.ps1 -NoBrowser
```

`update-windows.ps1` fetches and checks out exact branch authority, installs/verifies the canonical Windows runtime lock, starts the checkout-bound BodyRig service, verifies launcher state + health, and then automatically runs the rig-window planner **read-only**. A successful update therefore ends by printing the single safest next physical command instead of requiring a separate status/planner step.

When the intended identity is known, pass scope directly to the update so the automatic plan is immediately Person/source-bound:

```powershell
.\update-windows.ps1 -NoBrowser -PersonId '<person-32hex>' -PerformerId '<stash-performer-id>' -BodyId '<operator-alias>'
```

Or, when the canonical Person can be resolved uniquely from the performer:

```powershell
.\update-windows.ps1 -NoBrowser -PerformerId '<stash-performer-id>' -BodyId '<operator-alias>'
```

`-PreferredJobId '<job-id>'` can also be forwarded to the planner. `-PerformerId` and `-BodyId` must always be supplied together; this is checked before Git/service mutation begins.

The automatic planner runs in a separate PowerShell 7 process after service/revision authority is verified. Planner ambiguity or a missing `pwsh` does **not** convert a successful update into a failed update: it emits a warning and requires an explicit scoped planner invocation instead. Use `-SkipPlan` only when you deliberately want update/start without automatic planning.

For already-valid historical physical evidence, the same updater can re-enter its exact evidence revision safely:

```powershell
.\update-windows.ps1 -Revision '<40-char-sha>' -NoBrowser
```

Historical mode is fail-closed. The requested SHA must be a Git commit reachable as an ancestor of the freshly fetched `origin/main`, and that exact commit must contain its own Windows runtime lock, runtime-lock validator, launcher and acceptance-status tooling before the currently running BodyRig service is stopped. The target revision is then checked out detached, its own Windows dependency lock is installed and verified, and the restarted service must report that exact revision.

Automatic rig-window planning is intentionally **skipped** in `-Revision` mode. Historical revisions may predate the planner, and the command that selected the historical checkout already chains directly into that revision's own `physical-acceptance-status.ps1`. Follow that revision-bound status command rather than asking current policy to reinterpret old evidence.

After a Gate A or later physical acceptance evidence has been selected for continuation, do **not** pull, switch branches or edit tracked files until that exact chain is deliberately completed or abandoned.

## 1. Rerun the planner after each physical step

The normal update already prints an initial plan. After executing exactly one recommended current-revision action, rerun:

```powershell
.\plan-rig-window.ps1
```

If the performer id and local BodyId alias are known, preserve the same scope:

```powershell
.\plan-rig-window.ps1 -PerformerId '<stash-performer-id>' -BodyId '<operator-alias>'
```

If several BodyRig Person profiles are bound to the same performer, or you otherwise want to make the target explicit, add the canonical Person id:

```powershell
.\plan-rig-window.ps1 -PersonId '<person-32hex>' -PerformerId '<stash-performer-id>' -BodyId '<operator-alias>'
```

Person scoping is fail-closed. UI jobs, Gate-A rescue, downstream acceptances and interrupted recovery are only considered for the resolved Person. If unscoped job history contains multiple Persons, the planner stops and requires `-PersonId` or `-PerformerId` instead of guessing. If `-PersonId` and `-PerformerId` disagree with the canonical Person profile, planning stops. Standalone physical sessions are constrained by the selected performer/body authority; unscoped standalone evidence from multiple performers is also ambiguous and stops planning.

If one specific historical UI job is the intended continuation, add `-PreferredJobId '<job-id>'`. The job can establish Person intent when no stronger Person/performer scope is supplied. A preferred job only wins ties at the same physical progress; it never displaces farther valid evidence.

### Unified physical-progress order

The planner does not treat “Gate-A rescue”, “acceptance”, “session” and “interrupted recovery” as independent first-match buckets. They are assessed read-only and ranked together by how much expensive/physical work has already been preserved:

1. **Existing downstream acceptance / session-attached acceptance** — structural ranks: `release=60`, `quest-attestation=50`, `quest-probe=40`, `windows-attestation=30`, `windows-probe=20`; a fully complete chain ranks `100`.
2. **Committed Gate A** — rank `16`; the persistent `bodyrig-acceptance.json` already exists, so a merely validatable rescue must not displace it.
3. **Validated Gate-A-only rescue** — rank `15`; clone/recovery/fitter already exist and the real Gate-A validator passes against temporary output, but Gate A still has to be committed.
4. **Completed physical clone session before Gate A** — rank `10`.
5. **Interrupted recovery with intact complete package** — rank `8`; reconstruction and fitter do not rerun.
6. **Interrupted recovery with intact SiTH reconstruction** — rank `5`; reconstruction does not rerun, fitter does.
7. **Fresh profiled physical preflight/reconstruction** — rank `0`, permitted only if every reusable candidate fails validation or authority checks.

Timestamp is only a tie-breaker within the same progress rank. `-PreferredJobId` is also only a same-rank tie-breaker. Thus a newer Gate-A failure cannot displace an older Quest acceptance, a validatable Gate-A rescue cannot displace already committed Gate-A bytes, and an interrupted package cannot displace a completed clone session merely because it is newer.

A pre-Gate-A completed session and a committed Gate A both report `gate-a` as the relevant gate, but the authority layer distinguishes them by persistent bytes: the pre-Gate-A session points at a prospective acceptance directory that does not yet contain `bodyrig-acceptance.json`; committed Gate A does.

### Existing and historical downstream acceptance

UI-job acceptance directories and acceptance directories already attached to standalone physical sessions are structurally inspected before selection. A standalone session is therefore not artificially treated as “only a session” if its `clone_output/acceptance` has already advanced through Windows or Quest.

If the selected non-terminal evidence belongs to the current revision, the canonical physical acceptance status engine emits its exact next command. If it belongs to an older BodyRig revision, revision mismatch is **not** treated as a reason to reconstruct. The planner emits a guarded `update-windows.ps1 -Revision <evidence-sha>` command, then invokes that historical revision's own `physical-acceptance-status.ps1` against the exact acceptance/session evidence. The updater fetches `origin/main` and independently proves ancestor authority before any checkout/service mutation.

Structurally **complete** historical evidence has no later checkout command where that proof could be deferred. It therefore has a stricter rule: before it may stop the planner as complete, its revision must already be proven as an ancestor of the locally fetched `origin/main`. Normal `update-windows.ps1` refreshes that ref immediately before auto-planning. If the ref is absent or ancestry cannot be proven, the complete historical candidate is rejected rather than trusted optimistically.

If the furthest authority-valid chain is already complete, the planner stops and explicitly refuses to recommend fresh reconstruction.

### Validated Gate-A rescue

A failed body-build that already completed clone/recovery/fitting is assessed with the **real Gate-A validator** using temporary output. If it is the furthest remaining valid candidate, the planner emits:

```powershell
.\resume-body-job.ps1 -JobId '<job-id>'
```

This path does **not** rerun clone, recovery or the SiTH fitter. The real resume builds the replacement Gate A in a sibling staging directory first; only after that full validation succeeds are old partial Gate-A/fidelity outputs preserved as quarantine evidence and the validated replacement promoted.

You can explicitly run the same source-preserving assessment yourself:

```powershell
.\resume-body-job.ps1 -JobId '<job-id>' -AssessOnly
```

`-AssessOnly` creates no persistent BodyRig evidence and does not run the Windows fidelity renderer.

### Completed physical clone sessions — current or historical

A completed source-bound physical clone session is reusable even when Gate A was never run. On current `main`, the planner emits the session's canonical Gate-A next command. If the session belongs to an older safe ancestor revision, the planner emits:

```powershell
& .\update-windows.ps1 -Revision '<session-sha>' -NoBrowser; if ($?) { & .\physical-acceptance-status.ps1 -SessionReport '<session-report>' }
```

This deliberately re-enters the producer revision and continues from the exact session bytes instead of repeating PHALP/4D-Humans/SiTH merely because `main` moved forward.

### Interrupted package/reconstruction recovery

For failed/interrupted body jobs belonging to the scoped Person on the exact current BodyRig revision, the planner asks the existing BodyRig service recovery engine whether retained private evidence can be reused. Two canonical modes exist:

- **adopt complete package** — a complete source-bound package survived; expensive reconstruction **and fitter** do not rerun;
- **resume fit only** — completed SiTH reconstruction survived; expensive reconstruction does not rerun, but the fitter runs again from the retained exact reconstruction authority.

The planner calls the read-only wrapper equivalent of:

```powershell
.\resume-interrupted-body-job.ps1 -JobId '<job-id>' -AssessOnly
```

Only an `available=true` plan with `expensive_reconstruction_rerun=false` is eligible. The mutating command is emitted, never executed by the planner:

```powershell
.\resume-interrupted-body-job.ps1 -JobId '<job-id>'
```

### Fresh reconstruction is the last resort

Only when no reusable scoped acceptance, validated Gate-A rescue, completed physical session, complete package or retained SiTH reconstruction validates may the planner fall back to fresh profiled physical preflight/reconstruction.

With a performer/body pair supplied, the next command routes through checkout-bound `bodyrig-status.ps1`, which delegates to the canonical profiled first-run doctor. The crash-resilient recovery bridge can still reuse source-hash/adapter/revision-bound segment checkpoints inside retained observation workspaces if the canonical recovery path reaches them. Do not manually copy checkpoint files between workspaces.

## 2. Execute exactly one recommended next command

Run the command printed by update/planner. Do not manually reconstruct a shorter command and do not skip directly to fresh SiTH merely because it is familiar.

After a normal current-revision command finishes, rerun the same scoped planner command. If the planner deliberately switches to an older evidence revision, follow the `physical-acceptance-status.ps1` command printed immediately after that switch instead. Older revisions may predate `plan-rig-window.ps1`; that is expected and is why the historical-switch command chains directly into the selected revision's canonical status engine.

The flow should either advance to a later valid stage, report an already-complete chain, or explain why every reuse route is invalid before permitting fresh reconstruction.

## 3. Human/physical evidence boundary

The planner and assessment modes can prove byte lineage, package validity, skin/topology structural QA, runtime materialization, retained reconstruction/package authority and checkout authority. They **cannot** create or infer:

- human visual/fidelity PASS;
- real Windows/Quest renderer PASS;
- new source observations;
- source-derived anatomy/hair/eyes/face review authority;
- full digital-twin M5/M6 activation.

Those gates still require the actual rig, real source bytes and explicit human review where the canonical contracts require them.
