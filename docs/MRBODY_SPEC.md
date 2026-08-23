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

## Provenance

V1 records only bounded metadata: creation time, source kind/count, synthetic-avatar marker, and pinned pipeline stage/adapter/revision identifiers. Source filenames are intentionally not portable provenance.
