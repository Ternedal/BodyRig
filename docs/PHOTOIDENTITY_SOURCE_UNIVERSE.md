# Photoidentity source-universe audit

BodyRig must distinguish **we did not scan it** from **we scanned it but cannot safely identify the target person**.

`audit-photoidentity-source-universe.ps1` is a source-only inventory gate. It does not reconstruct or render anything and it grants no photoidentity capability.

## Preconditions

The operator requires:

- Windows / PowerShell 7+;
- an exact clean BodyRig checkout;
- saved Stash API configuration for the current Windows user;
- persistent storage authentication already `QUALIFIED` across the required two cold boots.

Storage qualification is required before locality is audited. Otherwise an inaccessible SMB file could be misclassified as absent source data.

## Exhaustion authority

The Stash inventory is fetched page by page against the server-advertised `findScenes.count`.

The audit fails closed if:

- the count changes while pages are being read;
- a non-final page is short;
- a scene appears on more than one page;
- a returned scene no longer contains the requested performer;
- the server count exceeds the explicit safety bound.

Only after every advertised scene is retrieved exactly once may `stash_inventory_exhausted=true` be written.

## Identity boundary

Every scene is separated into:

1. **single-performer** — the named Stash performer is the only performer attached to the scene;
2. **multi-performer** — the named performer is present in metadata, but other performers are also present.

Single-performer, projection-safe, locally readable video can enter the existing source-analysis route without inventing a target selector.

Multi-performer media is deliberately **not** treated as resolved. Stash metadata proves only that the target performer occurs somewhere in the scene; it does not identify a PHALP/OpenPose track. BodyRig therefore emits `multi_performer_identity_resolution_required=true` and keeps these files outside reconstruction/source-detail authority until a separate source-grounded track attestation exists.

The existing recovery `aggregate-*` track id is not identity authority: production recovery selects strong source-local PHALP tracks independently and hashes those ids for bodyprint provenance. It must not be repurposed as cross-video biometric identity.

## Privacy boundary

The public source-universe receipt contains counts only. It contains no:

- source paths or filenames;
- image/video bytes;
- face embeddings or biometric vectors;
- Stash API key;
- storage credential.

`biometric_identity_inference_used=false`, `generic_guessing_permitted=false`, `reconstruction_permitted=false`, `human_review_render_permitted=false`, and `production_activation=false` are fixed boundaries of this audit.

## Operator

After storage authentication is physically cold-boot qualified:

```powershell
.\audit-photoidentity-source-universe.ps1 -PerformerId '42'
```

A PASS means the Stash inventory itself was completely enumerated. It does **not** mean all media is identity-resolved, and it does not mean the digital clone is ready.
