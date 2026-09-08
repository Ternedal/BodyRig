# BodyRig handoff

_Last updated: 2026-09-08_

## Canonical repository authority

BodyRig has one normal software/run authority: **exact clean current `main`**.

Historical PR heads, old comments and frozen evidence branches are not current operator authority merely because they once passed CI. Existing physical evidence remains bound to the exact BodyRig revision, package/runtime bytes and receipts recorded in that evidence; later merges never rewrite historical authority.

The current operator path is checkout-bound and fail-closed. A global/stale BodyRig install must not authorize a physical next command. Fresh physical `body-build` creation is additionally revision-bound: the local clean checkout revision, running BodyRig service revision and enqueued job revision must all match exactly.

Repository-level enforcement is not yet complete: issue #138 remains open because GitHub currently reports `main` as unprotected and the repository has no ruleset requiring the exact-green PR checks. This is an admin/configuration blocker, not a software or evidence state that can be bypassed in code.

## Product definition: full digital twin

Issue #89 is the canonical completion definition. A photorealistic body/avatar is necessary but is **not** the finished product.

A released digital twin is one auditable Person Revision that binds the same real person across:

- body proportions/anatomy and source-derived skin/appearance;
- face identity and face-secondary detail;
- source-derived hair;
- source-derived eyes/iris/cornea;
- hands, fingers, feet, toes, fingernails and toenails;
- source-grounded wardrobe/clothing/footwear, including material, layering, attachment and deformation authority;
- VoiceRig-owned voice;
- source-derived personality;
- ModelRig + VoiceRig audition/review;
- Motor State v2 motion/expression/gesture/gaze/posture/speech realization;
- exact WindowsPlayer and Quest-class realization evidence.

Every identity-bearing component requires explicit provenance/review authority. A component is not complete merely because it is visible in a texture or preview.

## Full digital-twin software status

The **M1–M6 software chain is landed on `main`**. The remaining product blockers are real source/physical/human evidence for a concrete Person, not missing milestone architecture.

- **M1 — release contract/status:** fail-closed digital-twin readiness above body release and Person assembly.
- **M2 — hands/feet/nails:** source capture, renderer evidence, explicit human review and finalized authority.
- **M3 — wardrobe/footwear:** source-visible inventory/capture, renderer/deformation evidence, explicit human review and finalized authority.
- **M4 — Person Revision composition:** create-only authority binding exact Person assembly/audition, M2, M3, promoted `.mrbody`, BodyPrint and deterministic Motor State v2 embodiment evidence.
- **M5 — Windows/Quest realization:** exact-M4-bound WindowsPlayer + Quest-class realization with renderer/deformation/human-attestation lineage.
- **M6 — canonical release:** create-only final digital-twin release; only valid M6 may set `digital_twin_ready=true` and `production_activation=true`.

Operator hardening is also landed:

- one checkout-bound read-only `bodyrig-status.ps1` routes physical preflight → physical acceptance → high-fidelity continuation → M4/M5/M6 status;
- performer-bound preflight delegates to the canonical source doctor and emits the doctor-owned production clone command;
- `/api/v1/operator-authority` exposes the exact running BodyRig service revision without leaking checkout-path authority;
- `start-revision-bound-body-build.ps1` requires PowerShell 7+, exact clean local HEAD, healthy BodyRig service, service revision == checkout revision, one unambiguous Person and no competing active body-build before enqueue;
- revision-bound body-build enqueue carries `expected_bodyrig_revision` server-side; the manager lock covers authority-check → enqueue → returned-job revision validation, and a drifted queued job is cancelled before its physical subprocess can start;
- interrupted body-build resume also requires running-service revision == clean checkout revision and verifies the resumed/enqueued job revision;
- mixed selectors, checkout drift, invalid platform authority, body/revision mismatch, library drift and false release-complete states fail closed;
- status tooling distinguishes missing Person evidence from missing implementation;
- current Gate A accepts the canonical anatomy-aware appearance receipt while preserving legacy aggregate skin-QA;
- a historical completed clone that failed only at a later Gate-A validator contract can use the explicit cross-revision rescue path without rerunning recovery/fitting, provided the original evidence still validates;
- retained/high-fidelity Windows/WSL operators no longer assign PowerShell's read-only automatic `$HOME` variable; default SiTH root discovery remains `<WSL home>/.local/share/bodyrig/sith`;
- Stash source ranking rejects explicit VR/stereo/panoramic inputs and high-resolution approximately 2:1 projection-ambiguous geometry before the flat observation path;
- stale/manual source manifests and observation checkpoints are revalidated downstream, and the built-in OpenCV analyzer independently rejects projection-ambiguous decoded frame geometry before HOG/Haar work;
- canonical observation selection now requires feasible high-fidelity coverage with at least one `face_visibility >= 0.72` observation and one `full_body_visibility >= 0.72` observation under the existing overlap/per-source constraints before expensive SiTH work begins.

## Current high-fidelity body/avatar software chain

The trunk contains the full high-fidelity body/avatar continuation:

`Stash/source → decode-qualified + projection-safe observation → mandatory face/full-body coverage → retained reconstruction → subject anatomy candidate/audit → anatomy promotion → source hair review/deformation/promotion → eye/iris review/fingerprint/rebuild/promotion → face-secondary runtime/review/promotion → promoted .mrbody → package-bound human review → fresh Gate A → Windows → Quest → final body release`.

Recent anatomy work on `main` includes source/appearance diagnostics, improved texture correspondence, normal-aware subject-anatomy fitting and exact-bake bounded scoring/line search. Those machine metrics remain comparison/selection evidence; they do not manufacture a human anatomy or visual-fidelity PASS.

Important boundaries:

- projection-ambiguous VR/panoramic material must fail closed rather than being treated as flat-camera evidence;
- mandatory face/full-body observation coverage must be feasible before reconstruction; bypassing the source-quality gate is not a valid production path;
- retained reconstruction must not be rerun merely to manufacture cleaner evidence;
- preview/review artifacts are not component authority by themselves;
- promotion does not silently mutate baseline source evidence;
- hair/eye/face review-only runtimes cannot grant body or component completion;
- human visual/deformation authority remains genuinely human;
- body/platform release is necessary but still not the full digital-twin M6 release.

## Canonical operator entry point

Start from exact clean current `main`:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
git fetch origin
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
.\bodyrig-status.ps1
```

`git status --short` must be empty.

After Stash health/search has identified the intended performer, use the same router for source-bound preflight:

```powershell
.\bodyrig-status.ps1 -PerformerId '<stash-performer-id>' -BodyId '<operator-alias>'
```

When the current physical path requires a **fresh `body-build`**, start it only through the revision-bound launcher from the same exact clean checkout and with the BodyRig service restarted from that checkout if necessary:

```powershell
.\start-revision-bound-body-build.ps1 -PerformerId '<stash-performer-id>'
```

You may instead pass exactly one canonical `-PersonId`. The launcher fails closed if the service revision differs from local HEAD, if performer→Person resolution is missing/ambiguous, or if another body-build is already queued/running. On success it emits the revision-bound `job-...` id and the canonical `watch-body-build.ps1` monitor command.

As evidence is created, continue through the same router with the relevant selector:

```powershell
.\bodyrig-status.ps1 -SessionReport '<physical-session-report>'
.\bodyrig-status.ps1 -AcceptanceDir '<physical-acceptance-dir>'
.\bodyrig-status.ps1 -PreviewJobId '<hfpreview-id>'
.\bodyrig-status.ps1 -CompositionAuthorityDir '<m4-authority-dir>' -AcceptanceDir '<physical-acceptance-dir>'
```

Follow only the checkout-authorized emitted next command. `-Serial` and `-LibraryRoot` are forwarded only where their canonical downstream status engine owns them.

Once a fresh Gate A freezes a package/revision for the physical acceptance chain, do not pull, switch branches or edit tracked files until that chain is deliberately completed or abandoned.

## Historical Gate-A rescue

A real historical body job, `job-efcbf73d85464d68a90379cf7f9c2c50`, completed clone/recovery/fitting and produced `.mrbody`, then failed because the old Gate-A skin validator did not understand the anatomy-aware appearance receipt.

The reusable validator fix and explicit historical rescue path are both landed on current `main`. If the original local job/evidence still exists, try the checkout-bound rescue **before** rerunning PHALP/SiTH:

```powershell
pwsh -NoProfile -File .\resume-body-job.ps1 -JobId 'job-efcbf73d85464d68a90379cf7f9c2c50'
```

The rescue is fail-closed: producer and validator revisions stay distinct; original session/readiness/package/proof/identity bytes are revalidated; package bytes are not rebuilt; recovery/fitter are not rerun; previous partial Gate-A/fidelity output is quarantined. Success must report `resumed_without_clone_rerun=true` and still does **not** create human/physical PASS by itself.

If the original evidence is missing, drifted or otherwise invalid, do not reconstruct authority from memory; use the current canonical physical path instead.

## Remaining real work

The open product backlog is intentionally physical/human:

- #2 real video → source-derived BodyPrint/package on target rig;
- #3 exact fitted package → real Windows/Quest acceptance;
- #4 real-video visual identity/fidelity;
- #5 real SiTH reconstruction/skinning quality;
- #6 real Stash performer/source selection and production clone;
- #50 one coherent Person with human-approved anatomy, skin, hair, eyes/iris/cornea and face-secondary detail;
- #89 one complete Person Revision through M2/M3/M4/M5 and canonical M6.

One separate repository-administration blocker remains:

- #138 protect `main` with required exact-green CI / no-force-push / no-delete repository rules. Live verification on 2026-09-08 still reports `protected=false` and no repository rulesets. This requires authorized GitHub administration; software or CI evidence cannot substitute for it.

Do not close the physical/human issues from CI, fixtures, generated screenshots or software-only evidence.

## Open PR / historical branch discipline

Classify old/open PRs deliberately:

- **#196 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE:** source-derived skin PBR v2; current head `9e5026fd8f879784d354f81b00231991227f1d66`, exactly one commit ahead / zero behind #209 `main`, and exact-head software-green (`ci` `34204358571`; `windows-log-handle-regression` `34204358559`). Its three candidate blobs are the exact reviewed #132 blobs. CI does **not** grant physical skin/SSS/visual-fidelity or promotion authority. Fresh safe-source baseline/candidate package evidence plus real human visual review is still required before any explicit merge/promotion decision.
- **#208 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE:** PHALP temporal sampling v3; current head `f6cb88735df67c9a143d91edce57e73ef8c2ccd8`, exactly one commit ahead / zero behind #209 `main`, with the exact 18 blobs from the prior software-green integration head and unchanged reviewed PHALP/HMR2 runtime blobs. Exact-head software validation is green (`ci` `34205290162`; `windows-log-handle-regression` `34205290343`). CI does **not** prove throughput benefit or identity/anatomy preservation. Fresh revision-bound exact-main baseline + exact-candidate body-builds, machine A/B, real human visual review and a later explicit promotion decision remain mandatory.
- **#132 — HISTORICAL PBR LINEAGE:** historical source-derived PBR v2 revision `db3839b793b73f72d7d1d6006b873ad5954671dd`; keep as revision-bound lineage/evidence reference. #196 is the current-main integration candidate; do not silently rebase or merge #132 as current authority.
- **#134 — HISTORICAL THROUGHPUT LINEAGE:** historical recovery temporal-sampling v3 head `e891c03f6cb477414896a6f80157ab1e3d99d901`; exact bytes passed the current CI contract via validation-only PR #194 (`ci` `34190046670`; `windows-log-handle-regression` `34190046649`). #208 is the current-main integration candidate. Preserve #134's historical revision-bound lineage rather than treating it as merge authority.
- **#60 — SUPERSEDED CANDIDATE:** closed unmerged; its clean runtime core was ported forward. Its hard-coded 2026-09-03 baseline/A-B operator harness is historical design evidence only and must not be treated as current operator authority.
- **#63 — FROZEN EVIDENCE:** historical Gate-A lineage; reusable validator/rescue software is represented on current `main`, but the frozen branch remains historical evidence rather than normal merge authority.
- **#121 — SUPERSEDED DOC/CANDIDATE LINE:** its exact reviewed three-file PBR delta was ported forward; keep #121 closed rather than merging stale lineage.
- **#109 — SUPERSEDED DOCS:** its intent is incorporated by the current handoff; do not merge its old base onto modern `main`.

Use these meanings consistently:

- `LANDED` — effective content is already on trunk;
- `SUPERSEDED` — later work replaced the branch/approach;
- `FROZEN EVIDENCE` — branch identity must remain available for historical physical evidence;
- `ACTIVE/DRAFT CANDIDATE` — deliberate unlanded delta still needs its own validation and explicit evidence/promotion decision.

## Non-negotiable evidence rules

Never:

- synthesize or infer a human/physical PASS;
- rebind historical Gate-A/package/runtime evidence to new bytes;
- rerun expensive reconstruction merely to manufacture authority;
- hand-edit evidence JSON or delete create-only evidence to force a retry;
- bypass checkout-bound status/next-command authority;
- bypass revision-bound physical body-build startup when a fresh body-build is required;
- bypass projection/source-quality gates to force expensive reconstruction;
- substitute arbitrary PATH tools where an exact pinned runtime owns authority;
- treat source outfit as persistent body identity;
- call a body/avatar release, M4 composition or CI-green M5/M6 software a completed digital twin.

## Handoff discipline

Every meaningful BodyRig PR should state:

- exact base and validated head SHA;
- scope and non-scope;
- authority/activation boundary;
- automated validation performed;
- physical/human validation still required;
- whether it supersedes, stacks on or is already represented by another integration line.

Update this file whenever current trunk authority, canonical operator routing, the physical handoff or the next hard blocker changes.
