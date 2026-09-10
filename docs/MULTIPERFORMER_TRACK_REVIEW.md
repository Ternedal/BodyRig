# Multi-performer source track review

BodyRig does not infer that the strongest, largest or longest PHALP track in a scene is the requested Stash performer.

A multi-performer source therefore needs a separate identity-attestation chain before any target-isolated source sample can contribute photoidentity evidence.

## Source discovery

`discover-photoidentity-multiperformer-sources.ps1` re-fetches a stable, exhaustive performer-scoped Stash scene inventory after persistent storage qualification and path-map refresh.

It publishes a path-free public candidate manifest plus a private exact-source index. Discovery does not hash source media yet, choose a person, render human evidence or grant reconstruction authority.

The discovery result explicitly keeps `target_track_selected=false`, `biometric_identity_inference_used=false`, `generic_guessing_permitted=false`, `reconstruction_permitted=false`, `human_review_render_permitted=false` and `production_activation=false`.

## Machine track stage

`bodyrig.photoidentity_multiperformer_track_runner` invokes the exact pinned 4D-Humans/PHALP/NMR recovery environment through BodyRig's existing atomic WSL file protocol.

For each source it may expose only the exact source-media SHA-256, source-local PHALP track ids, actual observed timestamps (`tracked_time == 0` only), detector confidence and PHALP bounding boxes in upstream `(x, y, width, height)` form.

The machine never selects the requested performer. Appearance embeddings remain private to PHALP and are not BodyRig identity authority.

## Source-frame review and human identity attestation

`prepare-photoidentity-multiperformer-track-review.ps1` accepts one discovery candidate, runs pinned PHALP review, verifies the exact source SHA-256 and materializes real source-frame review sheets.

After inspecting those source-derived sheets, an operator may run `record-photoidentity-multiperformer-track-attestation.ps1` with one listed `TrackCandidateId`, a deliberate `QualityNote`, and explicit `-ConfirmIdentity`.

The create-only receipt binds exact BodyRig revision, Stash performer/scene, source SHA-256, machine PHALP review SHA-256, selected source-local track id, review-sheet SHA-256 and the public/private review hashes.

This receipt proves **which observed track is the requested performer**. It does not prove that every PHALP rectangle contains only that performer.

## Target-isolation candidate materialization

`materialize-photoidentity-multiperformer-target-source.ps1` consumes the exact human-attested review root and creates native source-crop candidates.

For each already reviewed observed PHALP sample it reuses the exact source-frame PNG bytes, verifies the stored frame hash, applies only the clamped native PHALP TLWH rectangle and writes the resulting PNG crop. It performs no bbox interpolation, resize, inpainting, occlusion removal or generative synthesis.

Crucially, this machine stage remains:

- `target_isolation_human_review_required=true`;
- `target_isolated_source_authority=false`;
- `photoidentity_source_evidence_authority=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

A PHALP bbox is a locator, not proof that another performer does not overlap the crop.

## Human target-isolation attestation

The operator reviews the actual source crops printed by the materializer and records only the samples that contain the requested performer without visible cross-person contamination:

`record-photoidentity-multiperformer-target-isolation.ps1 -CandidateRoot <root> -SampleId <one-or-more ids> -ConfirmTargetIsolation -QualityNote <note>`

The create-only receipt revalidates every selected source-frame and crop SHA-256 and grants `target_isolated_source_authority=true` **only with `authority_scope=accepted-samples-only`**.

Unselected samples receive no authority. The receipt still requires `photoidentity_source_evidence_authority=false`, `reconstruction_permitted=false`, `production_activation=false`, `bbox_interpolation_used=false`, `source_pixels_resized=false`, `occlusion_removal_used=false`, `generative_pixels_used=false`, `biometric_identity_inference_used=false` and `generic_guessing_permitted=false`.

The original multi-performer video must never be routed directly into the single-person analyzer merely because a track id was human-attested.

## Next authority gate

Target-isolated sample authority is not photoidentity sufficiency. The next stage is source-only detail enrichment over only the accepted exact crops, followed by the normal domain sufficiency rules. Missing detail remains insufficient; no analyzer may infer hidden identity-critical anatomy.

## Non-authority

Discovery, track review, identity attestation, candidate materialization and target-isolation attestation are not body reconstruction, bodyprint recovery acceptance, photoidentity sufficiency, human avatar fidelity acceptance, Gate A, Windows/Quest acceptance or production activation.

The existing recovery/bodyprint wire contract remains unchanged.
