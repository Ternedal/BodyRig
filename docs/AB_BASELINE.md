# Shared physical A/B baseline

`start-ab-baseline.ps1` is the canonical operator entrypoint when the active PBR-v2 and recovery-throughput-v3 draft candidates are both going to receive fresh physical comparison evidence.

It exists to avoid paying for two identical expensive current-main baseline reconstructions while preserving exact revision and candidate-byte authority.

## Start one retained current-main baseline

Run only from exact clean current `main`, with the local BodyRig service already started/restarted from that same checkout:

```powershell
cd C:\Users\admin\Desktop\BodyRig-git
.\update-windows.ps1 -Branch main -NoBrowser -SkipPlan

.\start-ab-baseline.ps1 `
  -PerformerId "42"
```

You may pass exactly one canonical `-PersonId` instead of `-PerformerId`.

Before any physical job is enqueued, the launcher fetches current `origin/main` and both active candidate refs and validates `contracts/ab-baseline-candidates-v1.json` fail-closed. Each candidate must be exactly one commit ahead / zero behind current main, have exactly the reviewed changed-file set, and every candidate file must have its reviewed Git blob SHA. The PBR candidate is bound across all three reviewed files; the throughput candidate is bound across all 18 reviewed files.

Only after that preflight does the wrapper call `start-revision-bound-body-build.ps1` with `-RetainPrivateWorkspaceForAb`. The existing revision-bound launcher still independently requires clean local HEAD == running BodyRig service revision == enqueued job revision and persists the exact A/B retention marker before physical worker start.

After enqueue, `start-ab-baseline.ps1` fetches main and both candidate refs again. If main or either candidate ref moved, it refuses to publish baseline-plan authority and attempts to cancel the newly created UI job through the canonical local job-cancel endpoint. A job for which this post-enqueue authority check failed must not be used as the shared dual-candidate baseline even if the physical process later finishes.

A stable enqueue writes a create-only local plan under:

```text
%LOCALAPPDATA%\BodyRig\ab-baseline-plans\<job-id>.json
```

The plan binds the exact baseline main revision, both exact candidate revisions/refs, the reviewed candidate-contract SHA-256, the body-job/Person identity and the revision-bound private-workspace retention marker. It is comparison-only and cannot grant physical acceptance, promotion or production activation.

## Monitor the baseline

Use the exact job id printed by the launcher:

```powershell
.\watch-body-build.ps1 -JobId '<baseline-job>'
```

The baseline must succeed normally. Do not start a candidate merely to work around a failed baseline.

## PBR v2 comparison

After the retained baseline succeeds, the same job can provide the current-main package and retained reconstruction for the strict PBR A/B path:

```powershell
.\run-pbr-ab-from-body-job.ps1 `
  -BaselineJobId '<baseline-job>'
```

That wrapper independently revalidates the succeeded body job, exact current main, safe-source ancestry, managed retained workspace and PBR candidate ref before producing comparison-only machine/render evidence. Human visual review remains mandatory.

Because the throughput candidate transition intentionally switches the checkout and running BodyRig service away from `main`, finish/generate the PBR machine/render comparison you want from the retained baseline **before** starting the throughput candidate job.

## Recovery-throughput comparison

The same succeeded baseline job is the baseline side of the throughput comparison, but throughput still requires a **separate fresh succeeded physical body-build from the exact throughput-candidate revision** using the same Person/source authority.

From the exact clean baseline `main` checkout, after the shared baseline has succeeded, start the candidate side only through the plan-bound transition wrapper:

```powershell
.\start-throughput-candidate-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>'
```

The wrapper revalidates the create-only baseline plan, the succeeded retained safe-source baseline body job, and the live 3/3 + 18/18 candidate byte contract **before** switching branches. It then uses `update-windows.ps1` to update/restart BodyRig from the exact plan-bound throughput candidate ref, requires checkout HEAD == service revision == the plan candidate revision, and starts the candidate through `start-revision-bound-body-build.ps1` using the exact Person from the baseline plan.

`update-windows.ps1` itself now refuses to stop a verified BodyRig service while any `body-build` is `queued`, `running` or `cancelling`, and fails closed if the active-job list cannot be inspected. Therefore the candidate transition cannot silently interrupt another physical body build merely to switch revisions.

After enqueue the candidate wrapper re-fetches both `origin/main` and the throughput candidate ref. If either moved from the revisions bound by the baseline plan, it refuses candidate-run-plan authority and attempts to cancel the new job. A stable candidate start writes a create-only `bodyrig-throughput-candidate-run-plan` under `%LOCALAPPDATA%\BodyRig\ab-baseline-plans\` and prints the exact monitor and machine A/B commands.

After the candidate job succeeds, remain on that exact clean candidate checkout and run the candidate-owned machine audit, immutable review-bundle builder and explicit human-review receipt chain. Do not switch back to `main` until that exact candidate evidence chain is deliberately completed or abandoned.

The throughput machine audit and human review remain comparison evidence only. They do not merge or promote the candidate.

## Authority boundary

These launchers do not:

- create a human or physical PASS;
- make either draft candidate mergeable from CI alone;
- rebind historical Lauren evidence;
- bypass projection or source-quality gates;
- activate a package or production release.

Historical projection-unsafe Lauren evidence remains historical FAIL. A fresh shared baseline must still satisfy the normal current-main physical source and reconstruction gates.
