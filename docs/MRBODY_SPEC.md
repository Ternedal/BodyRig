# `.mrbody` v1

`.mrbody` is a versioned data-only ZIP container. It must not contain scripts, executables, DLLs, plugins, model checkpoints or Python pickle objects.

## Required payload

```text
manifest.json
checksums.json
avatar.vrm
bodyprint.json
provenance.json
thumbnail.png
```

Optional V1 motion payloads are limited to `motions/idle.vrma`, `walk.vrma`, `talk.vrma`, and `gesture_01..03.vrma`.

`avatar.vrm` is the authoritative visual runtime asset. `bodyprint.json` is the authoritative portable physical/behavioural profile. Build-engine tensors are never authoritative runtime identity.

Import is fail-closed: fixed paths only, no traversal/backslashes/duplicates/encryption, bounded entry sizes and total expansion, exact SHA-256 payload map, canonical v1 metadata, finite/range-valid bodyprint values, and GLB v2 container checks for VRM/VRMA.

Installation/replacement is atomic: validate a temporary sibling completely, then replace the known-good profile in one operation.

## Portable identity

A production high-fidelity `.mrbody` does not use the operator's local alias as its portable manifest id. The operator alias (for example `performer-123`) remains useful for physical-clone session naming, while the package manifest id is a canonical `bodyid-<24 lowercase hex>` derived by the `bodyrig-portable-identity` v1 authority.

The identity material is path-free and binds the source-byte set, canonical recovery proof, canonical visual-identity evidence and subject track. Alias and source paths are excluded from canonical identity. The external fitter and Gate A both re-bind the receipt to the exact persistent clone evidence before accepting its body id.

Production provenance contains exactly one `identity_content` stage with adapter `bodyrig.portable_identity` and revision equal to the 24-hex suffix of the canonical body id. Gate A promotes the accepted package under canonical `<bodyid>.mrbody` and preserves the create-only portable-identity receipt as byte-bound acceptance evidence.

See `docs/PORTABLE_IDENTITY.md` and `contracts/portable-identity-v1.schema.json` for the identity derivation, source-byte TOCTOU boundary and strict validation rules.

## Provenance

V1 records only bounded metadata: creation time, source kind/count, synthetic-avatar marker, and pinned pipeline stage/adapter/revision identifiers. Source filenames are intentionally not portable provenance.
