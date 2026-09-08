# PBR v2 physical A/B review

This runbook prepares a revision-bound visual comparison for the current source-derived skin PBR v2 candidate without granting physical, renderer, release, or production authority.

## What the runner proves

`run-pbr-ab-physical-review.ps1` compares current `main` (LEFT / baseline) with the remote PBR candidate branch (RIGHT / candidate).

Before it builds anything, it requires:

- Windows and PowerShell 7+;
- a clean local `main` checkout;
- local `main` to equal current `origin/main`;
- the candidate branch to resolve to exactly one commit ahead of `main`;
- the candidate diff to contain only the three reviewed PBR-v2 files;
- a verified safe-source convergence checkpoint **or** explicit baseline-clone + retained-identity-workspace paths;
- current rig/SiTH setup authority;
- a current `sith-input-v1/reconstruction.json` and `reconstruction-authority.json`.

For convergence-backed reuse, both the convenience launcher and strict runner read the same `contracts/pbr-ab-source-policy-v1.json`. The policy currently requires safe-source floor `905fb0e9e9b67ad009fb707164474caf827a93a6` (#188) to be a Git ancestor of the retained checkpoint's `bodyrig_revision`.

The strict runner then:

1. creates a detached worktree for the exact candidate commit;
2. validates the same retained reconstruction under both baseline and candidate code;
3. hashes the entire retained `sith-input-v1` tree;
4. rebuilds a fresh baseline `.mrbody` from the retained reconstruction;
5. proves the retained tree is byte-identical;
6. rebuilds a fresh candidate `.mrbody` from the **same** retained reconstruction;
7. proves the retained tree is byte-identical again;
8. verifies each package's `manifest.builder.revision` against the exact baseline/candidate Git SHA;
9. runs the clean appearance-only machine A/B gate with both expected revisions;
10. renders the same four canonical Windows views for both packages using one common baseline renderer build;
11. rechecks the retained reconstruction bytes and both remote refs;
12. writes a comparison-only `run-authority.json`, `review.html`, and `REVIEW-NEXT.txt`.

For convergence mode, `run-authority.json` also records the retained-source mode, shared policy hash, safe-source floor revision and retained checkpoint revision. Explicit raw workspace mode is labelled `explicit-expert-recovery` and deliberately claims no checkpoint ancestry authority.

A successful runner result still requires human visual review. It does not merge the PBR candidate and it writes no acceptance or production activation.

## Canonical shared-baseline path

When throughput A/B and PBR A/B are both planned, do **not** pay for two independent current-main reconstructions merely because their evidence consumers differ. Use the shared dual-candidate baseline plan so both candidates are frozen to exact reviewed bytes before physical work begins.

Start only from exact clean current `main`, with the running BodyRig service bound to the same revision:

```powershell
cd C:\Users\admin\Desktop\BodyRig-git
.\update-windows.ps1 -Branch main -NoBrowser -SkipPlan

.\start-ab-baseline.ps1 `
  -PerformerId "42"
```

You may pass exactly one canonical `-PersonId` instead of `-PerformerId`.

Record the returned `job-...` id and let the baseline reach `succeeded`:

```powershell
.\watch-body-build.ps1 -JobId '<baseline-job>'
```

That exact succeeded job can be the baseline job for the recovery-throughput comparison **and** the retained source for PBR A/B. For a shared-plan run, the canonical PBR operator entrypoint is:

```powershell
.\run-pbr-ab-from-body-job-plan-bound.ps1 `
  -BaselineJobId '<baseline-job>'
```

Do not substitute `run-pbr-ab-from-body-job.ps1` as the operator entrypoint for the shared-plan flow. The lower-level body-job wrapper is still used internally, but the canonical launcher adds the terminal routing that binds the explicit human decision back to the same immutable shared baseline plan.

The canonical launcher delegates the expensive machine/render work to `run-pbr-ab-from-body-job.ps1`, then requires and revalidates:

- `run-authority.json`;
- `body-job-source-authority.json`;
- `body-job-plan-authority.json`;
- `machine-ab.json`;
- both canonical render sets;
- `review.html`;
- exact run/source hashes referenced by the plan authority;
- comparison-only authority with no physical acceptance, promotion or production activation.

Only after that chain is intact does it atomically replace `REVIEW-NEXT.txt` with a command to `record-pbr-ab-human-review-from-plan.ps1`. The generated decision and quality-note placeholders are deliberately non-runnable until the operator has actually reviewed all four canonical LEFT/RIGHT views.

For the retained body-job source itself, the lower-level body-job wrapper remains intentionally stricter than generic explicit-workspace mode. Before delegating to `run-pbr-ab-physical-review.ps1`, it requires:

- the canonical persisted job to be `bodyrig-ui-job` v1, `kind=body-build`, `status=succeeded`;
- the job revision to equal exact clean current checkout HEAD **and** freshly fetched `origin/main`;
- an exact `bodyrig-ab-baseline-retention` v1 marker persisted before worker start;
- canonical UI job paths for clone output, session, log, Gate A and fidelity evidence;
- the private workspace path to come from the producer job log, not an operator-supplied path;
- that workspace to live directly under BodyRig's managed `identity-workspaces` root and belong to the same Person;
- completed retained `sith-input-v1/reconstruction.json` plus `reconstruction-authority.json`;
- the same `contracts/pbr-ab-source-policy-v1.json` safe-source ancestry floor used by convergence mode.

After the strict PBR runner succeeds, the body-job wrapper re-runs the body-job source validator and refuses terminal authority if the job JSON, producer log, retained reconstruction, reconstruction authority, source policy or main revision changed. It writes create-only `body-job-source-authority.json`; the shared-plan wrapper additionally writes `body-job-plan-authority.json`, binding the source/run receipts to the immutable dual-candidate plan.

A normal UI body build is unchanged: successful standard jobs still delete the private identity workspace. Retention occurs only after an explicit A/B-retention request has been revision-bound and persisted while the job is still queued. The retained workspace remains local/build-only and never becomes part of the portable `.mrbody` or runtime.

For `lauren-phillips-test-01`, old projected-source evidence remains historical FAIL and cannot satisfy this path. The reusable body job must be a **fresh succeeded current-main job** created after the safe-source floor; no historical evidence is rebound.

## Fast path: latest safe verified convergence for one body

When the retained reconstruction came from the normal fidelity-convergence flow rather than a shared revision-bound UI body job, the convenience launcher can locate it for you:

```powershell
cd C:\Users\admin\Desktop\BodyRig-git

git fetch origin
git switch main
git pull --ff-only origin main
git status --short

.\run-latest-pbr-ab-physical-review.ps1 `
  -BodyId "lauren-phillips-test-01"
```

`run-latest-pbr-ab-physical-review.ps1` searches only local fidelity-convergence roots matching the explicit `BodyId`, newest first. Recency is only a search order and carries **no** safety authority. A run is usable only when all of the following hold:

- its latest checkpoint passes `bodyrig.fidelity_checkpoint_verify_cli`, including every bound artifact hash;
- the checkpoint body alias exactly matches the requested `BodyId`;
- the checkpoint's `bodyrig_revision` is a resolvable Git commit in this checkout;
- merge ancestry satisfies the shared retained-source policy floor.

The safe-source floor is deliberate. Its base already contains the downstream projection-safety and unified projection-policy chain, and #188 adds mandatory strong face plus full-body observation coverage before expensive SiTH reconstruction. A pre-floor checkpoint can therefore be perfectly intact at the byte level and still be unsuitable as new visual evidence.

For `lauren-phillips-test-01`, historical projected-source/reconstruction evidence remains historical FAIL evidence. The convenience launcher must reject it rather than rebind it to a new PBR comparison. If no post-floor retained convergence exists and no fresh revision-bound retained body job exists, the correct path is to run a fresh current-main fidelity convergence first.

After selecting a safe verified work root, the convenience launcher delegates to the same strict `run-pbr-ab-physical-review.ps1` path described below. The strict runner independently revalidates the same shared policy before using the checkpoint, so manual convergence-root selection cannot bypass the source floor.

## Explicit invocation from a retained convergence run

Use this form when you want to choose a particular fidelity-convergence work root yourself:

```powershell
.\run-pbr-ab-physical-review.ps1 `
  -ConvergenceWorkRoot "<path-to-fidelity-convergence-work-root>"
```

The runner verifies the latest checkpoint, validates the checkpoint revision against the same shared safe-source policy used by the fast path, and only then uses its `current_baseline_clone_output`, `current_identity_workspace`, body alias and display name. A known historical/pre-safe-source run is rejected even when supplied manually.

## Explicit retained-workspace invocation

If the retained reconstruction did not come from a convergence work root or a revision-bound retained UI body job:

```powershell
.\run-pbr-ab-physical-review.ps1 `
  -BaselineCloneOutput "<path-to-baseline-clone-output>" `
  -IdentityWorkspace "<path-to-retained-identity-workspace>"
```

`BaselineCloneOutput` is the directory containing `bodyrig-sith-fitter-config.json` and a `clone` subdirectory. `IdentityWorkspace` must contain the completed `sith-input-v1` reconstruction and its current reconstruction authority. This is an expert/recovery path with no checkpoint revision to prove. The runner does not manufacture a safe-source ancestry claim for it, and it must not be used to recycle known projection-unsafe historical evidence.

## Candidate branch

The default candidate ref is:

```text
candidate/skin-pbr-v2-current-main-20260908
```

The runner fetches and freezes the exact remote SHA at start, then fetches again before publishing terminal run authority. If either `origin/main` or the candidate ref moves during the run, the run fails closed and no terminal `run-authority.json` is published.

## Output

The strict runner's default output is under `%LOCALAPPDATA%\BodyRig\pbr-ab\...`. The body-job wrappers default under `%LOCALAPPDATA%\BodyRig\pbr-ab-body-job\...`. A completed strict run contains:

```text
baseline/<body>.mrbody
candidate/<body>.mrbody
machine-ab.json
baseline-render/
candidate-render/
run-authority.json
review.html
REVIEW-NEXT.txt
```

Body-job mode additionally writes:

```text
body-job-source-authority.json
```

Shared-plan body-job mode additionally writes:

```text
body-job-plan-authority.json
```

After the explicit plan-bound human review, the run also contains:

```text
human-review.json
plan-bound-human-review-authority.json
```

Open `review.html` to compare LEFT (baseline) and RIGHT (candidate) for:

- front-full;
- three-quarter-full;
- side-full;
- face-front.

## Human decision

### Shared-plan body-job mode

After reviewing all four views, use the exact command template written by `run-pbr-ab-from-body-job-plan-bound.ps1` to `REVIEW-NEXT.txt`. It calls only the shared-plan-bound recorder.

The shape is:

```powershell
.\record-pbr-ab-human-review-from-plan.ps1 `
  -BaselineJobId '<baseline-job>' `
  -RunDir '<pbr-run-dir>' `
  -Decision '<left|right|tie|reject-both>' `
  -QualityNote '<actual visual assessment>' `
  -ConfirmVisualReview
```

Replace both placeholders only after the visual review. The recorder validates the shared baseline plan, candidate contract, exact main/PBR/throughput revisions, run/source/plan authority receipts, machine A/B bytes and resulting canonical fidelity-review receipt before publishing create-only `plan-bound-human-review-authority.json`.

### Standalone convergence / expert modes

For standalone strict runs that are not tied to a shared dual-candidate baseline plan, use the exact generic command template produced by that strict run's `REVIEW-NEXT.txt`. Those modes continue to use `record-fidelity-ab-review.ps1` and do **not** manufacture shared-plan authority.

Decisions in either mode are:

- `right` — candidate is visibly preferable;
- `left` — baseline is visibly preferable;
- `tie` — no reliable preference;
- `reject-both` — neither is acceptable.

The canonical fidelity human-review receipt binds:

- exact left/right package SHA-256 values;
- exact left/right builder Git revisions;
- the machine A/B evidence SHA-256;
- one common renderer revision;
- both render-authority hashes;
- both render-set hashes;
- all eight individual canonical snapshot SHA-256 values;
- the operator decision and quality note.

In shared-plan mode the terminal plan-bound authority additionally binds that receipt back to the immutable baseline plan and both active candidate revisions. All of these receipts remain comparison-only and non-activating.

## Interpretation

A `right` decision is evidence that the candidate is preferable for this exact revision-bound appearance A/B. It is **not** automatically a full BodyRig physical PASS. Any subsequent merge/promotion must still respect the canonical physical/render/release gates and must not reinterpret older failed or unrelated human evidence.
