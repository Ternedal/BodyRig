# BodyRig handoff

_Last updated: 2026-09-06_

## Canonical repository authority

BodyRig has one canonical software trunk: `main`.

Normal new work and normal new physical runs start from an **exact clean current `main` checkout**. Old PR heads are historical development/evidence lineage, not normal operator software authority merely because they once had green CI.

Historical physical evidence is different: it remains bound to the exact BodyRig revision, package and runtime recorded in that evidence. Landing, closing, retargeting or rebasing code never rewrites historical physical authority.

Recent current-main hardening relevant to the next physical run:

- #104 — checkout-bound one-command full digital-twin status/next-gate authority;
- #105 — renderer-independent fidelity A/B evidence for appearance-only comparisons;
- #106 — missing M2/M3/M4/M5 state is reported as missing Person evidence, not missing implementation;
- #107 — Gate A skin QA accepts current canonical anatomy-aware appearance receipts while retaining the legacy aggregate risk gate;
- #108 — fail-closed historical Gate A rescue can revalidate an already completed clean clone under a newer validator without rerunning recovery/fitting.

## Product definition: full digital twin

Issue #89 is the canonical product-completion definition. A photorealistic body/avatar is **not** the finished product.

One auditable Person Revision must bind the same real person across:

- body proportions/anatomy and source-derived skin/appearance;
- face identity and face-secondary detail;
- hair;
- eyes/iris/cornea;
- hands, fingers, feet, toes and fingernail/toenail authority;
- source-grounded wardrobe/clothing/footwear with material, layering, attachment and deformation authority;
- VoiceRig-owned voice;
- source-derived personality;
- ModelRig + VoiceRig audition/review;
- BodyRig Motor State v2 embodiment;
- real WindowsPlayer + Quest-class realization;
- canonical final digital-twin release.

Every identity-bearing component needs explicit provenance/review authority. Visibility inside an avatar texture does not by itself make a component complete.

## Full digital-twin software status

The M1–M6 software chain is **implemented and landed on `main`**:

- **M1:** fail-closed digital-twin release/status model above Person assembly and body release (#90);
- **M2:** hands/feet/nails source, render/review and finalized release authority (#92);
- **M3:** wardrobe/clothing/footwear source, render/deformation review and finalized release authority (#94);
- **M4:** exact Person Revision composition binding body + voice + personality + presentation + deterministic Motor State v2 embodiment (#97);
- **M5:** exact-M4-bound real WindowsPlayer + Quest-class digital-twin realization authority (#100);
- **M6:** canonical create-only full digital-twin release; only valid M6 may set `digital_twin_ready=true` / `production_activation=true` (#102);
- **Operator status:** read-only checkout-bound `digital-twin-status.ps1` derives the next gate and withholds executable commands on wrong/dirty checkout or invalid evidence (#104).

This means the remaining blockers are **not missing milestone architecture**. They are source/physical/human evidence for one concrete Person.

## Integrated high-fidelity body/avatar software chain

The trunk contains the complete high-fidelity body/avatar continuation:

Stash/SiTH source → retained reconstruction/anatomy → anatomy promotion → source hair review/deformation/promotion → eye/iris isolation, review, fingerprint/rebuild/promotion → face-secondary runtime/review/promotion → exact final promoted `.mrbody` → package-bound high-fidelity human review → fresh promoted-package Gate A → canonical reference-wrapped Windows acceptance → canonical reference-wrapped Quest acceptance → canonical final body release.

Important authority boundaries remain intact:

- component preview/review is not physical PASS;
- promotion does not mutate the baseline source package in place;
- review-only runtimes cannot silently grant component completion;
- fresh Gate A freezes exact package/review/revision authority for its physical chain;
- Windows/Quest status exposes canonical reference wrappers;
- Quest adb authority comes from the pinned Unity Android SDK;
- generated `<...>` human quality-note placeholders fail closed;
- body `production_activation=true` requires the canonical body final release after real operator-supplied physical/human acceptance;
- body release is necessary for a full digital twin, but is not itself the M6 full-digital-twin release.

## First choice for the preserved historical physical run

Frozen PR #63 records real job:

```text
job-efcbf73d85464d68a90379cf7f9c2c50
```

That job completed Stash clone/recovery/fitting and produced a high-fidelity `.mrbody`, then failed at Gate A because the old validator only understood the legacy appearance receipt. The reusable validator fix and the generic rescue path are now on current `main` via #107/#108.

**Do not rerun PHALP/SiTH merely to retry that validator failure.** From an exact clean current `main`, try:

```powershell
pwsh -NoProfile -File .\resume-body-job.ps1 -JobId 'job-efcbf73d85464d68a90379cf7f9c2c50'
```

The rescue is deliberately fail-closed. It proceeds only if the local failed body job and original evidence still exist and revalidate, including:

- the job failed specifically at high-fidelity Gate A;
- original physical clone session is clean `pass/complete`;
- producer and current validator revisions remain distinct and explicit;
- original readiness/session/package/proof/identity/portable-identity evidence is intact;
- package is copied byte-identically;
- no recovery rerun;
- no fitter rerun;
- fresh Gate A skin/topology/runtime checks pass under current clean validator authority.

Existing partial Gate A/fidelity output is quarantined, never reused as new authority. A successful job continuation must report `resumed_without_clone_rerun=true` and still run the canonical Windows fidelity review before body revision/source-binding registration.

If the local historical evidence is gone or has drifted, rescue must fail closed. Only then move to a fresh physical source run.

## Fresh body/avatar physical path

For a fresh run, start from exact clean current `main` and use the repository runbooks/status tools rather than historical PR instructions.

Before high-fidelity continuation:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
git fetch origin
git switch main
git pull --ff-only origin main
git status --short
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1
pwsh -NoProfile -File .\list-high-fidelity-previews.ps1 -SucceededOnly
```

`git status --short` must be empty and preflight must PASS.

For an existing succeeded high-fidelity preview:

```powershell
$preview = 'hfpreview-0123456789abcdef0123456789abcdef'
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

Run exactly one emitted next command, perform the genuinely required human/physical review, then rerun status.

Once fresh Gate A exists, freeze that checkout until its physical acceptance chain completes or is deliberately abandoned.

The full body/avatar procedure is in `HIGH-FIDELITY-PHYSICAL-RUNBOOK.md`.

## Full digital-twin continuation after body authority

After exact body release and M4 composition evidence exist, use the checkout-bound digital-twin status as the canonical resume authority:

```powershell
pwsh -NoProfile -File .\digital-twin-status.ps1 <required Person/evidence arguments>
```

Follow only its emitted checkout-authorized `next_command`.

A concrete Person still needs real evidence for the applicable gates, including:

1. high-fidelity body anatomy/hair/eyes/face-secondary human review;
2. M2 hands/feet/nails source + renderer review authority;
3. M3 wardrobe/footwear source + deformation/render review authority;
4. exact M4 Person Revision composition across body/voice/personality/presentation/embodiment;
5. fresh real M5 WindowsPlayer and Quest-class realization with operator attestations;
6. M6 finalization only after all bound evidence still revalidates.

CI, fixtures, screenshots or software-generated evidence cannot substitute for these source/physical/human steps.

## Open PR / historical branch discipline

Intentionally open historical/candidate PRs are classified explicitly:

- **#60 — ACTIVE CANDIDATE:** recovery-throughput v3 / recovery-only max-15-fps temporal sampling. It is not present on normal `main` and still requires real baseline-vs-candidate physical A/B evidence before any promotion.
- **#63 — FROZEN EVIDENCE:** historical Gate A failure/resume lineage for `job-efcbf73d85464d68a90379cf7f9c2c50`. Its reusable validator and rescue implementation are now represented on current `main` by #107/#108; do not merge the old branch merely to obtain those fixes.

Before closing or porting an old PR, classify it deliberately as one of:

- `LANDED` — effective content is already in trunk;
- `SUPERSEDED` — a later implementation replaced it;
- `FROZEN EVIDENCE` — branch identity must remain available for historical physical evidence;
- `ACTIVE CANDIDATE` — still contains an intentional unlanded delta requiring its own validation.

## Non-negotiable evidence rules

Never:

- rebind historical Gate A/package/runtime evidence to new bytes;
- rerun expensive retained reconstruction merely to manufacture authority;
- treat the historical rescue as permission to accept missing/tampered producer evidence;
- hand-edit evidence JSON;
- manually delete create-only acceptance/review evidence to retry;
- substitute PATH adb for pinned Unity Android SDK adb;
- bypass status-generated canonical wrappers;
- synthesize or infer human/physical PASS;
- call a body/avatar release, M4 composition or CI-green M5/M6 software a completed digital twin without the concrete Person's required authorities.

## Handoff discipline

Every meaningful BodyRig PR should state:

- exact base SHA;
- exact head SHA after validation;
- scope and non-scope;
- authority/activation boundary;
- automated validation performed;
- physical validation still required;
- whether it supersedes, stacks on, or is already represented by another integration line.

Update this file whenever canonical trunk authority, the physical operator path, the full-digital-twin definition, or the next hard blocker changes.
