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

`enrich-photoidentity-multiperformer-target-crops.ps1` analyzes only the exact human-accepted target crops. It uses the pinned OpenPose and SCHP runtimes and may produce **machine observability candidates** only for:

- `eyes_detail`;
- `hands`;
- `feet`;
- `hair_hairline` — scalp/head hair plus hairline only;
- `skin_detail`.

The enrichment stage is deliberately not source-detail-quality authority. Its candidate score cannot by itself become photoidentity evidence. It remains `machine_observability_only=true`, `source_detail_quality_authority=false`, `photoidentity_source_evidence_authority=false`, `reconstruction_permitted=false` and `production_activation=false`.

SCHP/ATR has no authority for `eyebrows_detail`, `facial_hair_detail` or `body_hair_detail`. Those domains are never synthesized from the generic SCHP `Hair` class. The enrichment stage also has no authority for torso/chest, waist/hips, rear-body orientation, fingernails or toenails.

## Human source-detail quality attestation

The quality-attestation stage supports two deliberately different authority paths.

For the five machine-observable domains above, the operator may attest a domain/sample pair only when the exact current machine observability candidate is at or above the canonical `DETAIL_QUALITY_THRESHOLD` (currently `0.80`):

`record-photoidentity-target-crop-detail-quality.ps1 -CandidateRoot <root> -DetailRef <targetsample-id:domain> -ConfirmQuality -QualityNote <note>`

For the three hair-identity domains that the registered machine analyzers cannot honestly distinguish — `eyebrows_detail`, `facial_hair_detail`, and `body_hair_detail` — the operator must provide an explicit human source-quality score on the already human-isolated, hash-bound crop:

`record-photoidentity-target-crop-detail-quality.ps1 -CandidateRoot <root> -DetailRef <targetsample-id:eyebrows_detail:0.92> -DetailRef <targetsample-id:facial_hair_detail:0.90> -DetailRef <targetsample-id:body_hair_detail:0.88> -ConfirmQuality -QualityNote <note>`

Human-only hair claims require `quality_basis=explicit-human-source-review`, `human_visibility_attested=true`, and `machine_observability_used=false`. They must not contain `machine_adapter` or `machine_revision`. This is intentional: visible absence/minimal hair can be an observed subject-specific state when the crop is sufficiently clear, but absence of evidence is not converted into a neutral/default claim.

The receipt revalidates the exact target-isolation receipt, enrichment receipt, private analysis index and crop SHA-256. For machine-backed domains the selected adapter must match the pinned OpenPose/SCHP domain authority. A human note cannot rescue a sub-threshold machine-backed crop or an unregistered analyzer. Human-only hair still requires an explicit finite score at or above the same canonical quality threshold.

This stage grants `source_detail_quality_authority=true` for the explicitly selected source-domain claims, but still requires:

- `photoidentity_source_evidence_authority=false`;
- `generic_guessing_permitted=false`;
- `reconstruction_permitted=false`;
- `production_activation=false`.

The receipt is create-only and public/path-free. At most one crop per domain is attested for a given scene receipt.

## Aggregate human-reviewed multi-performer detail

`aggregate-photoidentity-multiperformer-detail-evidence.ps1` composes one or more target-crop quality receipts into a new `multiperformer-detail-evidence` bundle **before** nail/anatomy authority is added.

Every `-QualityReceipt` must be paired positionally with its exact human-reviewed `-CandidateRoot`. Before accepting any claim, aggregation replays the target-isolation receipt, target-crop enrichment receipt, private analysis index and selected crop bytes/provenance. A detached JSON receipt with merely well-formed SHA-256 strings is not authority.

The aggregation:

- starts from the exact canonical `human-parsing-evidence` bundle;
- preserves its observation rows, source-file count and scan-exhaustion fields unchanged;
- adds only source-detail claims from the supplied human quality receipts;
- rejects a multi-performer scene that overlaps the single-performer observation-row pool;
- rejects duplicate domain/scene authority;
- copies every source-quality receipt into `multiperformer-detail-source-authority` and binds each copy by SHA-256;
- accepts `human-reviewed-target-crop-detail-quality@1` only for the exact eight target-detail domains: eyes, hands, feet, scalp/hairline, exposed skin, eyebrows, facial hair and body hair;
- requires machine provenance for the original five machine-observable domains and forbids machine provenance for the three human-only hair domains;
- does not grant that adapter authority for rear-body, torso/chest, waist/hips, fingernails or toenails.

Aggregation is create-only, so it proves **all eight target-detail sufficiency domains in memory before creating any output path**. Each domain must meet its canonical distinct-scene requirement. A partial set — including only one qualifying scene for any domain that requires two — fails before `multiperformer-detail-evidence`, `multiperformer-detail-source-authority`, or the aggregation receipt is created. Persisted aggregation re-proves the same completeness on every later validation.

The central analyzer adapter for this intermediate bundle is `bodyrig-photoidentity-coarse-openpose-schp-human-target-detail-composite@1`. It preserves the canonical OpenPose/SCHP capabilities and adds only the human-review capabilities actually supported by accepted eyebrow/facial-hair/body-hair claims. It does not convert SCHP into authority for those domains.

If this complete aggregate exists, nail attestation uses it as its prior. Nail discovery itself remains bound to the original `human-parsing-evidence` bytes so its already-materialized source candidates cannot silently change. The nail receipt records both the immutable base hashes and the selected prior hashes.

`photoidentity-source-status.ps1` routes through this multi-performer chain before nails. It may list discovered candidates and pending human-review roots, but it never chooses the source candidate, PHALP track, accepted target sample or human-only hair quality on the operator's behalf. Nail routing is available only after the persisted aggregation validates, and a nail receipt must bind the exact aggregation observation/report SHA-256 values with `prior_stage=multiperformer-detail`.

The aggregate may improve normal distinct-scene sufficiency counts, but it still does not add nail/anatomy authority and does not activate production.

## Final source-chain and registry authority

Final registration revalidates the complete multi-performer lineage before those target-detail claims can survive into registered body-job authority.

`photoidentity-human-source-chain-v2` requires any final `human-reviewed-target-crop-detail-quality@1` claims to have a valid persisted aggregation at the same performer, BodyRig revision and baseline source authority. The nail receipt must point to the exact aggregation observation/report bytes, and the target-detail claims in the final anatomy bundle must exactly match the aggregation claims.

Body-job registry authority v3 copies the aggregation receipt and every SHA-bound quality receipt into the job's create-only `source-authority/multiperformer-detail` tree. `require_body_job_photoidentity_evidence` revalidates that persisted receipt set and its hashes on every later authority check. Removal, replacement or tampering therefore fails closed.

The durable registry replay understands the same split authority contract as live aggregation: machine provenance is mandatory for eyes/hands/feet/scalp-hairline/skin and forbidden for human-only eyebrows/facial-hair/body-hair claims. The registry path does not need the original private crop tree after registration because the full live source lineage was replayed before aggregation; it binds the exact human quality receipts, aggregation receipt and final claim set instead.

## Non-authority

Discovery, track review, identity attestation, candidate materialization, target-isolation attestation, machine detail enrichment and source-detail-quality attestation are not body reconstruction, bodyprint recovery acceptance, final registered photoidentity sufficiency, human avatar fidelity acceptance, Gate A, Windows/Quest acceptance or production activation.

Intermediate multi-performer aggregation is also not production authority by itself. It becomes usable only when the complete final nail/anatomy source chain is validated and registered through the body-job photoidentity gate.

The existing recovery/bodyprint wire contract remains unchanged.
