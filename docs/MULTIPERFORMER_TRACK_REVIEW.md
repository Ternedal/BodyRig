# Multi-performer source track review

BodyRig does not infer that the strongest, largest or longest PHALP track in a scene is the requested Stash performer.

A multi-performer source therefore needs a separate identity-attestation chain before any target-isolated source segment can contribute photoidentity evidence.

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

## Next authority gate: target isolation

The next required stage is to build target-isolated source evidence from the attested track, then review and bind that isolation result before it may enter the photoidentity evidence pool.

Until target-isolated source authority exists, the human receipt explicitly keeps:

- `target_isolated_source_authority=false`;
- `photoidentity_source_evidence_authority=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

The original multi-performer video must never be routed directly into the single-person analyzer merely because a track id was human-attested.

## Non-authority

Track discovery, review and identity attestation are not:

- body reconstruction;
- bodyprint recovery acceptance;
- photoidentity source sufficiency;
- human visual fidelity acceptance;
- Gate A;
- Windows or Quest acceptance;
- production activation.

The existing recovery/bodyprint wire contract is intentionally unchanged.
