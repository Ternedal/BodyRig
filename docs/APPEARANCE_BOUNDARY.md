# BodyRig appearance boundary

BodyRig owns the persistent **body identity and embodiment**, not the person's outfit.

## Ownership

BodyRig owns:

- source-derived body proportions / BodyPrint;
- body geometry and rig/skeleton;
- deformation behavior;
- skin/body-surface identity;
- face/head identity cues needed for the embodied person;
- portable `.mrbody` runtime bytes and their provenance.

BodyRig does **not** own:

- shirts, trousers, dresses, jackets or other garments;
- shoes as outfit items;
- glasses, hats, jewellery or other accessories;
- outfit selection, wardrobe state or outfit revisions.

Those belong to a separate appearance/outfit layer and must be replaceable without creating a new BodyRig body identity.

## Source video may still contain clothing

Real source video will normally show a clothed person. BodyRig may observe that clothing as reconstruction context and as an occlusion signal, but it must not treat the observed outfit as a permanent identity component.

The existing `visual_identity.coverage.clothing` field is therefore **observation metadata only**. It means that clothing/occlusion was visible in the source material; it is not a portable clothing asset and does not grant BodyRig ownership of the outfit.

## Portable fitter policy

`bodyrig-external-fitter-config` v1 keeps its historical `capabilities.clothing` field for format compatibility, but package-producing fitters must now set it to `false`.

Every `.mrbody` produced through the external high-fidelity fitter receives this provenance stage:

```json
{
  "stage": "appearance-boundary",
  "adapter": "bodyrig.garment-policy",
  "revision": "external-outfit-v1"
}
```

This stage means that the package is a BodyRig body asset and that garments/outfits are external appearance state.

## SiTH caveat

SiTH reconstructs the **observed visible surface**, so source garments can still influence intermediate geometry and texture. Setting the architectural boundary does not magically recover exact hidden anatomy from loose clothing.

For that reason the physical V1 quality gate must explicitly reject a candidate where the source outfit is visibly baked into the persistent body identity. Body-shape inference under occlusion is allowed; permanent source-garment geometry/texture is not.

Until a garment-neutral candidate is proven on the target rig, this remains a physical quality blocker rather than something CI can truthfully prove from fixtures.

## Future appearance layer

A future outfit/appearance asset should bind to a BodyRig `body_id` while remaining independently revisioned, for example:

```text
person revision
  -> body-rXXXX / bodyid-...
  -> outfit-rXXXX
  -> voice-rXXXX
  -> personality-rXXXX
```

Changing an outfit must not change the underlying BodyRig identity unless the body itself changes.
