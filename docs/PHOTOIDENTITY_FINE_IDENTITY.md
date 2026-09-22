# Photoidentical fine-identity source authority

BodyRig treats photoidentity as a source-grounded identity problem, not a realism problem. A plausible generic human prior is not authority for identity-critical detail.

This additive gate sits after the existing nail + rear/torso/waist anatomy source chain and before high-fidelity preview. It does not rewrite historical PhotoIdentity receipts.

## Required domains

Every domain requires at least two distinct real source scenes with exact sweep-source binding and source quality >= 0.80:

- `oral_teeth_detail` — visible teeth/dentition and oral appearance;
- `chest_breast_shape_detail` — source-specific chest/breast form, volume, placement and asymmetry;
- `nipple_areola_detail` — source-specific nipple/areola appearance and placement;
- `intimate_anatomy_detail` — source-specific intimate anatomy when full photoidentity is required;
- `distinctive_markers_detail` — scars, moles, birthmarks, tattoos, freckle clusters, pigmentation, piercing marks and other visible identity markers.

Missing source evidence blocks the photoidentical path. BodyRig does not substitute a generic anatomy guess.

## Privacy boundary

The private review manifest may contain local source paths and review-image paths. The persisted public attestation contains only source ordinals, scene/region identifiers, hashes, quality values and review provenance. Raw intimate/chest/oral review imagery is never copied into the public authority receipt.

The private distinctive-marker inventory must explicitly mark a complete review of:

`face_head`, `chest_breast`, `abdomen_waist`, `back`, left/right arms, hands, legs, feet and `intimate_region`.

An empty marker list therefore means "all required regions were reviewed and no marker was recorded", not "marker review was skipped".

## Operator flow

1. Complete the existing PhotoIdentity nail + anatomy source workflow.
2. Assemble reviewed source images for the five domains. Every row must refer to an exact `source_ordinal` from the existing BodyRig sweep; arbitrary external media is rejected.
3. Build the private review manifest:

```powershell
.\prepare-photoidentity-fine-identity-review-manifest.ps1 `
  -SweepRoot <SWEEP_ROOT> `
  -EvidenceCsv <PRIVATE_EVIDENCE_CSV> `
  -MarkerInventory <PRIVATE_MARKER_INVENTORY_JSON>
```

4. Record the human attestation with all five explicit confirmations:

```powershell
.\record-photoidentity-fine-identity-attestation.ps1 `
  -SweepRoot <SWEEP_ROOT> `
  -PrivateReviewManifest <PRIVATE_REVIEW_MANIFEST> `
  -ReviewedBy "<reviewer>" `
  -QualityNote "<what was visibly verified>" `
  -ConfirmOralTeethPhotoidentity `
  -ConfirmChestBreastShapePhotoidentity `
  -ConfirmNippleAreolaPhotoidentity `
  -ConfirmIntimateAnatomyPhotoidentity `
  -ConfirmDistinctiveMarkersPhotoidentity
```

5. Register the normal PhotoIdentity authority to the exact body-job if it is not already registered.
6. Register the additive fine-identity sidecar:

```powershell
.\register-photoidentity-fine-identity-authority.ps1 `
  -BodyJobId <JOB_ID> `
  -SweepRoot <SWEEP_ROOT>
```

High-fidelity preview revalidates this sidecar and persists both the sidecar receipt SHA-256 and the fine-identity attestation SHA-256 into the preview job lineage.

None of these receipts grants photoreal acceptance or production activation.


## Source-derived dental reconstruction

Photoidentical oral/teeth detail must not use the historical deterministic generic mouth/teeth generator. When `fineIdentityRequirement` is present, that generic path is blocked.

A local dental reconstruction adapter can now consume only the exact private `oral_teeth_detail` evidence that was already bound into the fine-identity attestation.

Adapter config format:

```json
{
  "format": "bodyrig-photoidentity-dental-reconstruction-adapter-config",
  "version": 1,
  "adapter": "your-pinned-dental-adapter",
  "revision": "exact-adapter-or-model-revision",
  "command": [
    "python",
    "adapter.py",
    "--bodyrig-dental-input",
    "<replaced-by-bodyrig>",
    "--bodyrig-dental-output",
    "<replaced-by-bodyrig>"
  ],
  "capabilities": {
    "oral_teeth_geometry": true,
    "oral_teeth_appearance": true,
    "source_grounded": true,
    "generative_identity_synthesis": false
  },
  "timeout_seconds": 3600
}
```

Run from an exact clean checkout:

```powershell
.\run-photoidentity-dental-reconstruction.ps1 `
  -SweepRoot <SWEEP_ROOT> `
  -AdapterConfig <DENTAL_ADAPTER_CONFIG>
```

The adapter receives a private input manifest whose review images are copied into a create-only workspace under hash-safe names. The adapter must write:

- `adapter-output/dental-source.vrm`
- `adapter-output/dental-reconstruction.json`

The candidate VRM must expose one `BodyRigSourceDentalIdentity` skinned node and one `BodyRigSourceDentalIdentityMesh` containing exactly the roles `mouth_interior`, `upper_teeth`, and `lower_teeth`. The dental surface must carry a source-derived texture. BodyRig independently validates the VRM structure, exact input/attestation hashes, adapter revision, source references, and the non-generative/non-generic authority boundary.

A successful run creates a **candidate only**. Human visual review remains mandatory; no face-secondary promotion or production activation is granted.


### Face-secondary review graft

For a package that carries `fineIdentityRequirement`, the face-secondary review runtime must now receive the exact source-derived dental candidate and reconstruction result. The operator rejects the photoidentical path if either file is absent or if their VRM/result/input-manifest/attestation lineage no longer matches the package requirement.

```powershell
.\build-high-fidelity-face-secondary-review-runtime.ps1 `
  -PackagePath <PROMOTED_BODYRIG_PACKAGE> `
  -OutputDir <FACE_SECONDARY_REVIEW_RUNTIME> `
  -DentalCandidatePath <DENTAL_WORKSPACE>\adapter-output\dental-source.vrm `
  -DentalResultPath <DENTAL_WORKSPACE>\adapter-output\dental-reconstruction.json
```

The graft copies the source-derived mouth/teeth surfaces and appearance into the review VRM but does not trust adapter skin weights. `upper_teeth` vertices are rebound to the destination package's canonical `smplx_head` skin joint; `mouth_interior` and `lower_teeth` are rebound to canonical `smplx_jaw`. The resulting runtime remains comparison-only and requires human review. Historical packages without `fineIdentityRequirement` retain the v1 generic review path, and supplying dental evidence to that path is rejected.
