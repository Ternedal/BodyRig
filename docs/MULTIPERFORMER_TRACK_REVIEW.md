# Multi-performer source track review

BodyRig does not infer that the strongest, largest or longest PHALP track in a scene is the requested Stash performer.

A multi-performer source therefore needs a separate identity-attestation chain before any target-isolated source evidence can contribute photoidentity evidence.

## Source discovery

`discover-photoidentity-multiperformer-sources.ps1` re-fetches a stable, exhaustive performer-scoped Stash scene inventory after persistent storage qualification and path-map refresh.

It publishes a path-free public candidate manifest plus a private exact-source index. Discovery does not hash source media yet, choose a person, render human evidence or grant reconstruction authority.

The discovery result explicitly keeps:

- `source_paths_persisted=false` in public evidence;
- `source_media_hashed_at_discovery=false`;
- `target_track_selected=false`;
- `biometric_identity_inference_used=false`;
- `generic_guessing_permitted=false`;
- `reconstruction_permitted=false`;
- `human_review_render_permitted=false`;
- `production_activation=false`.

## Machine track stage

`bodyrig.photoidentity_multiperformer_track_runner` invokes the exact pinned 4D-Humans/PHALP/NMR recovery environment through BodyRig's existing atomic WSL file protocol.

The dedicated bridge reuses the same repository, package, CUDA/cuDNN and licensed SMPL preflight as production recovery, but emits a separate review-only contract.

For each source it may expose only:

- the exact source-media SHA-256;
- source-local PHALP track ids;
- actual observed track timestamps (`tracked_time == 0` only);
- detector confidence;
- PHALP bounding boxes in upstream `(x, y, width, height)` form.

The result explicitly states:

- `target_track_selected=false`;
- `human_identity_attestation_required=true`;
- `appearance_embeddings_exported=false`;
- `source_paths_exported=false`;
- `biometric_identity_inference_used=false`;
- `generic_guessing_permitted=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

PHALP appearance features remain inside the private pinned tracker process and are not part of BodyRig's review contract.

## Source-frame review stage

`prepare-photoidentity-multiperformer-track-review.ps1` accepts exactly one candidate from the revision-bound discovery result, runs the pinned source-only PHALP review, verifies the same source SHA-256 on both Windows and WSL sides, and materializes source-derived review sheets.

Each track review sheet contains multiple actual source timestamps with an annotated full-frame context and a padded source crop derived from the PHALP TLWH box. The public review manifest stores hashes and source-local track ids only; exact media paths and review-sheet paths remain in the private index.

The machine still does not select the target performer. The prepared review remains:

- `target_track_selected=false`;
- `target_isolated_source_authority=false`;
- `photoidentity_source_evidence_authority=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

## Human identity attestation

After reviewing the listed source-derived review sheet, an operator may run `record-photoidentity-multiperformer-track-attestation.ps1` with exactly one listed `TrackCandidateId`, a deliberate `QualityNote`, and explicit `-ConfirmIdentity`.

The create-only receipt binds:

- exact BodyRig Git revision;
- Stash performer and scene ids;
- source candidate id and exact source-media SHA-256;
- machine track-review SHA-256;
- selected PHALP source-local track id;
- review-sheet SHA-256 and sample count;
- public/private review manifest hashes;
- the human identity note and UTC attestation time.

Receipt publication is atomic no-clobber: a concurrent or pre-existing human receipt cannot be silently overwritten.

A human track attestation resolves **which observed PHALP track is the requested performer for that exact source and review evidence**. It does not itself make the multi-person source safe for photoidentity analysis.

The receipt explicitly keeps:

- `target_isolated_source_authority=false`;
- `photoidentity_source_evidence_authority=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

The original multi-performer video must never be routed directly into the single-person analyzer merely because a track id was human-attested.

## Target-isolation review candidate

`prepare-photoidentity-target-isolation.ps1` consumes a valid human track-attestation chain and creates a separate target-isolation review candidate.

The operator preserves revision lineage instead of rewriting human evidence. The original track attestation keeps its own `attestation_revision`; the new candidate records a separate `isolation_operator_revision`. The PowerShell operator requires the attestation revision to be an ancestor of current HEAD before older human evidence may be continued on newer canonical code. Cross-lineage reuse fails closed.

The target-isolation stage then:

- reuses the exact pinned 4D-Humans/PHALP/NMR runtime;
- reruns PHALP on the exact source bytes;
- follows only the already human-attested source-local track id;
- requires the rerun canonical track fingerprint to equal the machine track review already bound by the human receipt;
- uses only actual observed PHALP states (`tracked_time == 0`), never predicted states;
- measures overlap between the target box and every other observed track over the whole target trajectory;
- evenly samples representative frames across the full observed target track rather than cherry-picking low-overlap frames;
- extracts each exact source frame and masks everything outside a 12% padded PHALP TLWH target box to black;
- creates a review tile showing source context with the target box beside the isolated candidate;
- creates one private contact sheet covering every sampled isolation candidate.

BBox overlap metrics are machine comparison/warning evidence only. They neither synthesize a human PASS nor automatically override what the human reviewer can actually see in the isolated pixels.

The machine candidate remains review-only:

- `machine_identity_selection=false`;
- `biometric_identity_inference_used=false`;
- `generic_guessing_permitted=false`;
- `human_isolation_review_required=true`;
- `target_isolated_source_authority=false`;
- `photoidentity_source_evidence_authority=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

The original multi-person source is never rewritten or relabeled as a single-performer Stash source.

## Human target-isolation attestation

After inspecting every source-context/isolation pair, an operator may run `record-photoidentity-target-isolation-attestation.ps1` with a deliberate `QualityNote` and explicit `-ConfirmIsolation` only when all shown isolated frames contain the requested performer and no visible pixels from another performer contaminate the isolated evidence.

The human gate rehashes the original source, the machine isolation evidence, the contact sheet, every source frame, every isolated frame and every review tile before publication. The receipt is atomic no-clobber and bound to the exact isolation candidate revision.

A PASS sets:

- `human_isolation_attested=true`;
- `all_isolation_samples_reviewed=true`;
- `visible_cross_person_contamination_absent=true`;
- `authority_scope=isolated-sampled-frame-set-only`;
- `target_isolated_source_authority=true`.

That authority is deliberately narrow: it applies **only to the exact hash-bound isolated PNG frame set that was shown to the reviewer**. It does not authorize the original multi-person video, unseen track timestamps, a generated video, or arbitrary future crops from the same track.

Even after a human isolation PASS, the receipt still keeps:

- `photoidentity_source_evidence_authority=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

## Next authority gate: isolated-frame importer/analyzer

A separate importer/analyzer contract must consume only the exact isolated frames enumerated and hash-bound by a target-isolation human receipt with `authority_scope=isolated-sampled-frame-set-only`.

That future stage must not:

- read the original multi-person video as analyzer input;
- treat the track identity receipt alone as single-person source authority;
- fabricate a Stash `performer_count=1` manifest for the original source;
- broaden authority from the reviewed sampled frame set to unseen timestamps;
- grant reconstruction or production merely because target isolation passed.

Only after the isolated frames are explicitly analyzed under a capability-bound photoidentity contract may they contribute photoidentity source evidence. Normal source-sufficiency and later human/physical gates still apply.

## Non-authority

Track discovery, track identity attestation and target-isolation attestation are not:

- body reconstruction;
- bodyprint recovery acceptance;
- photoidentity source sufficiency by themselves;
- human visual body-fidelity acceptance;
- Gate A;
- Windows or Quest acceptance;
- production activation.

The existing recovery/bodyprint wire contract remains intentionally unchanged.
