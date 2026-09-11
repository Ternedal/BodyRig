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

## Source-only detail enrichment

`enrich-photoidentity-multiperformer-target-crops.ps1` analyzes only the exact human-accepted target crops. It uses the pinned OpenPose and SCHP runtimes and may produce machine observability candidates only for:

- `eyes_detail`;
- `hands`;
- `feet`;
- `hair_hairline`;
- `skin_detail`.

The enrichment stage is deliberately not source-detail-quality authority. Its candidate score cannot by itself become photoidentity evidence. It remains `machine_observability_only=true`, `source_detail_quality_authority=false`, `photoidentity_source_evidence_authority=false`, `reconstruction_permitted=false` and `production_activation=false`.

It has no authority for torso/chest, waist/hips, rear-body orientation, fingernails or toenails.

## Human source-detail quality attestation

After reviewing the actual human-isolated source crop, an operator may attest only a domain/sample pair that already has machine observability at or above the canonical `DETAIL_QUALITY_THRESHOLD` (currently `0.80`):

`record-photoidentity-target-crop-detail-quality.ps1 -CandidateRoot <root> -DetailRef <targetsample-id:domain> -ConfirmQuality -QualityNote <note>`

The receipt revalidates the exact target-isolation receipt, enrichment receipt, private analysis index and crop SHA-256. The selected machine adapter must match the pinned OpenPose/SCHP domain authority. A human note cannot rescue a sub-threshold crop or an unregistered analyzer.

This stage grants `source_detail_quality_authority=true` for the explicitly selected source-domain claims, but still requires:

- `photoidentity_source_evidence_authority=false`;
- `generic_guessing_permitted=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

The receipt is create-only and public/path-free. At most one crop per domain is attested for a given scene receipt.

## Aggregate human-reviewed multi-performer detail

`aggregate-photoidentity-multiperformer-detail-evidence.ps1` composes one or more target-crop quality receipts into a new `multiperformer-detail-evidence` bundle **before** nail/anatomy authority is added.

The aggregation:

- starts from the exact canonical `human-parsing-evidence` bundle;
- preserves its observation rows, source-file count and scan-exhaustion fields unchanged;
- adds only source-detail claims from the supplied human quality receipts;
- rejects a multi-performer scene that overlaps the single-performer observation-row pool;
- rejects duplicate domain/scene authority;
- copies every source-quality receipt into `multiperformer-detail-source-authority` and binds each copy by SHA-256;
- uses the registered `human-reviewed-target-crop-detail-quality@1` claim authority only for eyes, hands, feet, hair/hairline and exposed skin;
- does not grant that adapter authority for rear-body, torso/chest, waist/hips, fingernails or toenails.

The central analyzer adapter for this intermediate bundle is `bodyrig-photoidentity-coarse-openpose-schp-human-target-detail-composite@1`. It has the same capability set as the canonical OpenPose+SCHP stage; it merely permits the additional **human-reviewed source path** for those five domains.

If this complete aggregate exists, nail attestation uses it as its prior. Nail discovery itself remains bound to the original `human-parsing-evidence` bytes so its already-materialized source candidates cannot silently change. The nail receipt records both the immutable base hashes and the selected prior hashes.

The aggregate may improve normal distinct-scene sufficiency counts, but it still does not add nail/anatomy authority and does not activate production.

## Next authority gate

The next separate hardening gate must teach the final human source-chain and body-job registry to persist and revalidate the multi-performer aggregation receipt plus its copied quality receipts. Only after that end-to-end lineage is verified may a final anatomy-attested sufficient bundle be registered against a body-build.

Until registration validates the complete source chain, avatar/reconstruction work remains blocked by the normal body-job photoidentity gate.

## Non-authority

Discovery, track review, identity attestation, candidate materialization, target-isolation attestation, machine detail enrichment, source-detail-quality attestation and intermediate multi-performer aggregation are not body reconstruction, bodyprint recovery acceptance, final registered photoidentity sufficiency, human avatar fidelity acceptance, Gate A, Windows/Quest acceptance or production activation.

The existing recovery/bodyprint wire contract remains unchanged.
