# BodyRig handoff

_Last updated: 2026-09-05_

## Canonical repository authority

BodyRig now has one canonical software trunk: `main`.

- PR #54 (`Person Studio: source-grounded photoreal person workflow`) is merged and closed.
- PR #83 (`High fidelity: integrate hair + eyes + face-secondary completion chain`) was merged into the #54 lineage before #54 landed.
- #54 landed on `main` as merge commit `442978a0efca258a892e7d74af3ca0eac9532229`.
- Exact pre-merge integrated head `5eda72ff68fd52ab928904eaa6e26c1d25f2628a` passed `ci` #1771 and `windows-log-handle-regression` #943.
- The #54 merge commit has zero file delta from that exact green pre-merge head, so the landed tree is byte-for-byte the validated integrated tree.

Normal new work starts from exact current `main`. Feature branches and old PR heads are historical development/evidence lineage, not current operator software authority merely because they once had green CI.

Historical physical evidence is different: it remains bound to the exact BodyRig revision, package and runtime recorded in that evidence. Landing, closing, retargeting or rebasing code never rewrites historical physical authority.

## Integrated high-fidelity software chain

The trunk now contains the complete software continuation:

Stash/SiTH source → retained reconstruction/anatomy → anatomy promotion → source hair review/deformation/promotion → eye/iris isolation, review, fingerprint/rebuild/promotion → face-secondary runtime/review/promotion → exact final promoted `.mrbody` → package-bound high-fidelity human review → fresh promoted-package Gate A → canonical reference-wrapped Windows acceptance → canonical reference-wrapped Quest acceptance → canonical final release.

Important authority boundaries remain intact:

- component preview/review is not physical PASS;
- promotion does not mutate the baseline source package in place;
- review-only combined runtimes cannot silently grant component completion;
- invalid create-only high-fidelity human-review receipts use the preserving recovery path only before fresh Gate A;
- fresh Gate A copies and freezes exact package-bound review authority and freezes the exact BodyRig revision for the rest of the physical chain;
- Windows/Quest status exposes canonical reference wrappers, not raw low-level acceptance commands;
- Quest adb authority comes from the pinned Unity Android SDK, never an arbitrary PATH adb;
- generated `<...>` human quality-note placeholders fail closed;
- `production_activation=true` can arise only from canonical final release after real operator-supplied physical/human acceptance.

## Canonical operator entry point

Before a fresh promoted-package Gate A exists:

```powershell
cd <YOUR-BODYRIG-CHECKOUT>
git status --short
git fetch origin
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
pwsh -NoProfile -File .\high-fidelity-rig-preflight.ps1
pwsh -NoProfile -File .\list-high-fidelity-previews.ps1 -SucceededOnly
```

Both `git status --short` calls must be empty and preflight must PASS.

Then select the intended persisted preview and use status as the sole source of the next canonical operator action:

```powershell
$preview = 'hfpreview-0123456789abcdef0123456789abcdef'
pwsh -NoProfile -File .\high-fidelity-physical-status.ps1 -PreviewJobId $preview
```

Run exactly one printed next command, perform any genuinely required human/physical review, then rerun status.

Once `prepare-high-fidelity-physical-acceptance.ps1` creates fresh Gate A, **freeze the checkout**. Do not pull, switch branch, edit tracked files or otherwise change the repo until that acceptance chain completes or is deliberately abandoned.

The full procedure is in `HIGH-FIDELITY-PHYSICAL-RUNBOOK.md`.

## Remaining real work

There is currently no known software-only blocker in the integrated high-fidelity acceptance chain. The remaining authority is deliberately real/manual:

1. run preflight on the actual BodyRig Windows/WSL rig;
2. select the intended succeeded persisted `hfpreview-...`;
3. if and only if status offers high-fidelity human-review recovery, preserve/archive the invalid receipt through the exact printed recovery command;
4. perform the final package-bound human review if status requires it;
5. create a fresh promoted-package Gate A;
6. run the real reference-wrapped Windows renderer/deformation probe and perform the actual human attestation;
7. run the real reference-wrapped Quest probe on Quest-class hardware and perform the headset attestation;
8. run canonical final release;
9. require final audited status with `production_ready=true` and `production_activation=true`.

CI, screenshots and software-generated evidence cannot substitute for those physical/human steps.

## Open PR / historical branch discipline

A number of older stacked component, recovery and performance PRs may still be open administratively even though the integrated high-fidelity line has landed. Do not infer that they are required operator branches.

Before closing or porting an old PR, compare its exact head against current `main` and classify it deliberately as one of:

- `LANDED` — its effective content is already in trunk;
- `SUPERSEDED` — a later implementation replaced it;
- `FROZEN EVIDENCE` — branch identity must remain available for historical physical evidence;
- `ACTIVE CANDIDATE` — it still contains a deliberate unlanded delta requiring its own validation.

Performance candidates such as recovery-throughput changes still require their own real A/B evidence before they can become production authority; speed alone or historical green CI is not enough.

## Non-negotiable evidence rules

Never:

- rebind historical Gate A/package/runtime evidence to new bytes;
- rerun expensive retained reconstruction merely to manufacture authority;
- use `accept-reconciled-physical-clone.ps1` as a shortcut for the high-fidelity release chain;
- hand-edit evidence JSON;
- manually delete create-only acceptance/review evidence to retry;
- substitute PATH adb for the pinned Unity Android SDK adb;
- bypass the status-generated reference wrappers;
- synthesize or infer human/physical PASS.

## Handoff discipline

Every meaningful BodyRig PR should state:

- exact base SHA;
- exact head SHA after validation;
- scope and non-scope;
- authority/activation boundary;
- automated validation performed;
- physical validation still required;
- whether it supersedes, stacks on, or is already represented by another integration line.

Update this file whenever canonical trunk authority, the physical operator path, or the next hard blocker changes.
