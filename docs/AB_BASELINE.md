> **A/B v1 lifecycle — completed 2026-09-10.** The PBR-v3 / recovery-throughput-v3 shared comparison cycle is finished and promoted under receipt SHA-256 `2daac171b018b0bdb813fb4698c17fa882ef8d130cd9df0ab7e87d7282c9850d`. `contracts/ab-baseline-candidates-v1.json` is now immutable historical evidence; it is not an active candidate contract. Repository immutability is bound by Git blob `703187fc8584cb3300f61d9ddb73eb886c27513f`; the original Windows run recorded checkout-byte SHA-256 `fa9ee08c715c216a4dce90e85a2bd699ed56f73eaad5f3fa444cd625110f6cf4`, which is retained as historical evidence rather than reused as a cross-platform file hash. `contracts/ab-baseline-cycle-state-v1.json` records that closure. `start-ab-baseline.ps1` and `preflight-ab-baseline.ps1` fail closed before physical work until a **new versioned candidate contract/lifecycle** is introduced. This retirement grants no physical acceptance, production activation, or release authority.

# Shared physical A/B baseline

`start-ab-baseline.ps1` is the canonical operator entrypoint when the active PBR-v3 and recovery-throughput-v3 draft candidates are both going to receive fresh physical comparison evidence.

It exists to avoid paying for two identical expensive current-main baseline reconstructions while preserving exact revision and candidate-byte authority.

The active PBR comparison candidate is the linear-light v3 replacement in PR #258. PR #196 is superseded historical PBR-v2 lineage and is not current shared-baseline authority.

## Start one retained current-main baseline

Run only from exact clean current `main`, with the local BodyRig service already started/restarted from that same checkout:

```powershell
cd C:\Users\admin\Desktop\BodyRig-git
.\update-windows.ps1 -Branch main -NoBrowser -SkipPlan

.\start-ab-baseline.ps1 `
  -PerformerId "42"
```

You may pass exactly one canonical `-PersonId` instead of `-PerformerId`.

Before any physical job is enqueued, `start-ab-baseline.ps1` automatically runs the read-only `preflight-ab-baseline.ps1` path. The preflight first validates current `origin/main`, both active candidate refs and `contracts/ab-baseline-candidates-v1.json` fail-closed. Each candidate must be exactly one commit ahead / zero behind current main, have exactly the reviewed changed-file set, and every candidate file must have its reviewed Git blob SHA. The PBR candidate is bound across all three reviewed files; the throughput candidate is bound across all 18 reviewed files.

The physical part of that preflight executes **inside the running BodyRig service**, not merely in the operator shell. This deliberately binds the fail-fast checks to the same service checkout, BodyRig Python, process environment and default tool lookup that the later UI body-build uses. The service-side preflight requires:

- exact clean service checkout revision == the candidate-authority `main` revision;
- exactly one canonical Person → Stash performer binding;
- no already-open BodyRig UI build for that Person;
- configured service-side `STASH_URL` and `STASH_API_KEY`;
- pinned reference-renderer readiness, including Unity/UniVRM and Android build support;
- live `check-rig-ready.ps1` readiness for the Windows Python lock, rig setup, recovery/PHALP, SiTH/OpenPose, checkpoint/model hashes and Stash health;
- an exact-performer `ffmpeg-one-frame-v1` probe with at least one locally decodable source;
- unchanged exact checkout authority after those live checks.

`check-reference-renderer-ready.ps1` does not open Unity or create renderer evidence. `check-rig-ready.ps1` is intentionally called without `-Out`, so the fail-fast preflight does not create session/readiness evidence. The source probe is metadata/decode readiness only. A successful preflight therefore means only that the expensive baseline is worth attempting; it grants no physical acceptance, human review, promotion or production activation.

After the service-bound live checks, `preflight-ab-baseline.ps1` re-fetches and revalidates exact `main` plus both candidate revisions/contract bytes. `start-ab-baseline.ps1` then performs a fresh candidate-contract validation again immediately before enqueue. This duplication is intentional because the live renderer/rig/source checks can take time.

Only after those fail-fast checks does the wrapper call `start-revision-bound-body-build.ps1` with `-RetainPrivateWorkspaceForAb` and the exact preflight-bound Stash performer identity. The revision-bound launcher still independently requires clean local HEAD == running BodyRig service revision == enqueued job revision and persists both the exact source-enqueue authority and A/B retention marker before physical worker start. The physical clone itself continues to revalidate its rig/source/reconstruction authorities at point of use; the preflight is not a substitute for those evidence-producing gates.

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

## PBR v3 comparison

After the retained baseline succeeds, the same job can provide the current-main package and retained reconstruction for the canonical plan-bound PBR A/B path:

```powershell
.\run-pbr-ab-from-body-job-plan-bound.ps1 `
  -BaselineJobId '<baseline-job>'
```

This launcher delegates the machine/render work to the strict body-job PBR runner, then revalidates the completed run/source/plan authority chain and atomically replaces `REVIEW-NEXT.txt` with the explicit shared-plan-bound human-review command. The decision and quality-note placeholders are deliberately non-runnable until the operator has reviewed all four canonical LEFT/RIGHT views and supplies a real assessment.

Do not substitute `run-pbr-ab-from-body-job.ps1` as the operator entrypoint for a shared-plan run. That lower-level wrapper remains part of the implementation chain, but the canonical launcher above is what preserves the terminal human-review binding introduced for the shared baseline plan.

Because the throughput candidate transition intentionally switches the checkout and running BodyRig service away from `main`, finish the PBR machine/render comparison **and its plan-bound human review** from the retained baseline before starting the throughput candidate job.

## Recovery-throughput comparison

The same succeeded baseline job is the baseline side of the throughput comparison, but throughput still requires a **separate fresh succeeded physical body-build from the exact throughput-candidate revision** using the same Person/source authority.

From the exact clean baseline `main` checkout, after the shared baseline has succeeded and the PBR plan-bound human review has been completed, start the candidate side only through the plan-bound transition wrapper:

```powershell
.\start-throughput-candidate-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>'
```

The wrapper revalidates the create-only baseline plan, the succeeded retained safe-source baseline body job, and the live 3/3 + 18/18 candidate byte contract **before** switching branches. It also requires the recorded PBR human-review gate and pins the candidate enqueue to the same reviewed Stash performer identity. It then uses `update-windows.ps1` to update/restart BodyRig from the exact plan-bound throughput candidate ref, requires checkout HEAD == service revision == the plan candidate revision, and starts the candidate through `start-revision-bound-body-build.ps1` using the exact Person/source authority from the reviewed chain.

`update-windows.ps1` itself now refuses to stop a verified BodyRig service while any `body-build` is `queued`, `running` or `cancelling`, and fails closed if the active-job list cannot be inspected. Therefore the candidate transition cannot silently interrupt another physical body build merely to switch revisions.

After enqueue the candidate wrapper re-fetches both `origin/main` and the throughput candidate ref. If either moved from the revisions bound by the baseline plan, it refuses candidate-run-plan authority and attempts to cancel the new job. A stable candidate start writes a create-only `bodyrig-throughput-candidate-run-plan` under `%LOCALAPPDATA%\BodyRig\ab-baseline-plans\` and prints the exact monitor and canonical continuation commands.

After the candidate job succeeds, remain on that exact clean candidate checkout and continue only through the plan-bound candidate evidence chain:

```powershell
.\continue-throughput-review-from-ab-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>'
```

That continuation revalidates the shared baseline plan, PBR sequencing gate, candidate-run receipt, exact candidate contract/ref/revision and succeeded job/source identities before it performs the machine audit and builds the immutable review bundle. The explicit human review remains a separate operator decision.

The throughput machine audit and human review remain comparison evidence only. They do not merge or promote the candidate.

## Authority boundary

These launchers do not:

- create a human or physical PASS automatically;
- make either draft candidate mergeable from CI alone;
- rebind historical Lauren evidence;
- bypass projection or source-quality gates;
- activate a package or production release.

Historical projection-unsafe Lauren evidence remains historical FAIL. A fresh shared baseline must still satisfy the normal current-main physical source and reconstruction gates.
