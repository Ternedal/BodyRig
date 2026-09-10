# Multi-performer source track review

BodyRig does not infer that the strongest, largest or longest PHALP track in a scene is the requested Stash performer.

A multi-performer source therefore needs a separate identity-attestation chain before any target-isolated source segment can contribute photoidentity evidence.

## Machine stage

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

## Human stage

This contract alone does **not** resolve a multi-performer source.

A later operator must materialize source-derived review frames/crops for the candidate track ids and a human must explicitly attest which source-local track is the requested performer. That attestation must bind exact source-media, review-frame, track-id and BodyRig revision hashes.

Until that human receipt exists, multi-performer media stays outside the photoidentity evidence pool.

## Non-authority

Track review is not:

- body reconstruction;
- bodyprint recovery acceptance;
- photoidentity source sufficiency;
- human visual fidelity acceptance;
- Gate A;
- Windows or Quest acceptance;
- production activation.

The existing recovery/bodyprint wire contract is intentionally unchanged.
