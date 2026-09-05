# BodyRig handoff

_Last updated: 2026-09-05_

## Canonical repository authority

BodyRig now has one canonical software trunk: `main`.

- PR #54 (`Person Studio: source-grounded photoreal person workflow`) is merged and closed.
- PR #83 (`High fidelity: integrate hair + eyes + face-secondary completion chain`) was merged into the #54 lineage before #54 landed.
- #54 landed on `main` as merge commit `442978a0efca258a892e7d74af3ca0eac9532229`.
- Exact pre-merge integrated head `5eda72ff68fd52ab928904eaa6e26c1d25f2628a` passed `ci` #1771 and `windows-log-handle-regression` #943.
- The #54 merge commit has zero file delta from that exact green pre-merge head, so the landed tree is byte-for-byte the validated integrated tree.
- PR #88 then bound new physical sessions to exact clean current `main`; its exact head passed `ci` #1773 and `windows-log-handle-regression` #945 before merge.

Normal new work starts from exact current `main`. Feature branches and old PR heads are historical development/evidence lineage, not current operator software authority merely because they once had green CI.

Historical physical evidence is different: it remains bound to the exact BodyRig revision, package and runtime recorded in that evidence. Landing, closing, retargeting or rebasing code never rewrites historical physical authority.

## Product definition: full digital twin

Issue #89 is now the canonical product-completion definition. A photorealistic body/avatar is **not** the finished product.

BodyRig is complete only when one auditable Person Revision represents the same real person across:

- body proportions/anatomy and source-derived skin/appearance;
- face identity and face-secondary detail;
- hair;
- eyes/iris/cornea;
- hands, fingers, feet, toes and explicit fingernail/toenail authority;
- source-grounded wardrobe/clothing/footwear with material, layering, attachment and deformation authority;
- VoiceRig-owned voice;
- source-derived personality;
- ModelRig + VoiceRig audition/review;
- motion/expression/voice-timing embodiment.

Every identity-bearing component needs explicit provenance/review authority. Visibility inside an avatar texture does not by itself make a component complete.

## Integrated high-fidelity body/avatar software chain

The trunk contains the complete high-fidelity **body/avatar** continuation:

Stash/SiTH source → retained reconstruction/anatomy → anatomy promotion → source hair review/deformation/promotion → eye/iris isolation, review, fingerprint/rebuild/promotion → face-secondary runtime/review/promotion → exact final promoted `.mrbody` → package-bound high-fidelity human review → fresh promoted-package Gate A → canonical reference-wrapped Windows acceptance → canonical reference-wrapped Quest acceptance → canonical final body release.

Important authority boundaries remain intact:

- component preview/review is not physical PASS;
- promotion does not mutate the baseline source package in place;
- review-only combined runtimes cannot silently grant component completion;
- invalid create-only high-fidelity human-review receipts use the preserving recovery path only before fresh Gate A;
- fresh Gate A copies and freezes exact package-bound review authority and freezes the exact BodyRig revision for the rest of the physical chain;
- Windows/Quest status exposes canonical reference wrappers, not raw low-level acceptance commands;
- Quest adb authority comes from the pinned Unity Android SDK, never an arbitrary PATH adb;
- generated `<...>` human quality-note placeholders fail closed;
- body `production_activation=true` can arise only from canonical body final release after real operator-supplied physical/human acceptance.

That body release is necessary for a digital twin, but it is no longer sufficient to call the Person a full digital twin.

## Canonical operator entry point for the body/avatar chain

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

The full body/avatar procedure is in `HIGH-FIDELITY-PHYSICAL-RUNBOOK.md`.

## Remaining real work

Under the full-digital-twin definition there **are** software blockers again. Issue #89 owns them.

Current missing explicit twin authorities:

1. hands/feet/nails source authority, reconstruction/material detail, review and promotion;
2. wardrobe/clothing/footwear source authority, reconstruction/materials, layering, attachment, deformation review and package representation;
3. digital-twin status/release composition that requires exact body + voice + personality + presentation + embodiment authority for one Person Revision;
4. end-to-end UI/operator status that distinguishes `avatar ready` from `digital twin ready`;
5. canonical digital-twin final release authority above the existing body release.

The existing Person model already versions body, VoiceRig voice and personality separately and binds them through an audition-backed assembly receipt. M1 adds a fail-closed digital-twin readiness layer above that assembly rather than weakening or replacing it.

The existing physical body chain still requires real/manual execution on the target rig before the body itself can be physically released:

1. run preflight on the actual BodyRig Windows/WSL rig;
2. select the intended succeeded persisted `hfpreview-...`;
3. perform any required package-bound human review;
4. create a fresh promoted-package Gate A;
5. run the real reference-wrapped Windows renderer/deformation probe and actual human attestation;
6. run the real reference-wrapped Quest probe and headset attestation;
7. run canonical body final release.

CI, screenshots and software-generated evidence cannot substitute for those physical/human steps, and body release alone cannot substitute for missing full-digital-twin authorities.

## Open PR / historical branch discipline

The remaining intentionally open historical/candidate PRs are classified explicitly:

- #60 — `ACTIVE CANDIDATE`: recovery-throughput v3; requires real A/B evidence before promotion.
- #63 — `FROZEN EVIDENCE`: retained historical Gate A resume lineage; do not reinterpret/merge it merely from CI.

Before closing or porting an old PR, compare its exact head against current `main` and classify it deliberately as one of:

- `LANDED` — its effective content is already in trunk;
- `SUPERSEDED` — a later implementation replaced it;
- `FROZEN EVIDENCE` — branch identity must remain available for historical physical evidence;
- `ACTIVE CANDIDATE` — it still contains a deliberate unlanded delta requiring its own validation.

## Non-negotiable evidence rules

Never:

- rebind historical Gate A/package/runtime evidence to new bytes;
- rerun expensive retained reconstruction merely to manufacture authority;
- use `accept-reconciled-physical-clone.ps1` as a shortcut for the high-fidelity release chain;
- hand-edit evidence JSON;
- manually delete create-only acceptance/review evidence to retry;
- substitute PATH adb for the pinned Unity Android SDK adb;
- bypass the status-generated reference wrappers;
- synthesize or infer human/physical PASS;
- call a body/avatar release a full digital twin while hands/nails, wardrobe or other required Person authorities are missing.

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
