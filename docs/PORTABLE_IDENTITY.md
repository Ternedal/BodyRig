# Portable identity v1

BodyRig V1 separates the **operator alias** from the **portable body identity**.

The operator may start a clone with an alias such as `performer-123`. That alias is useful for local session names and operator-facing artifacts, but it is not the runtime identity of the body. A production high-fidelity clone derives a canonical identifier with this form:

```text
bodyid-<24 lowercase hexadecimal characters>
```

The canonical identifier is the `.mrbody` manifest id used by Gate A, runtime materialization and downstream ModelRig-compatible body identity.

## Receipt

The authority is a create-only `bodyrig-portable-identity` v1 JSON receipt. Its exact fields are defined by `contracts/portable-identity-v1.schema.json` and include:

- canonical `body_id`;
- operator `requested_alias`;
- source count;
- path-free source-set SHA-256;
- canonical recovery-proof SHA-256;
- canonical visual-identity SHA-256;
- subject track id;
- authority `bodyrig.portable_identity` revision `1`.

The receipt contains no source paths, Stash credentials, frames, private observation workspaces, research model paths or checkpoints.

## Canonical identity derivation

`body_id` is content-addressed from identity material that intentionally excludes the operator alias and local source paths. The material contains:

1. receipt format/version;
2. source count;
3. the path-free source-byte-set digest;
4. canonical recovery-proof digest;
5. canonical visual-identity digest;
6. subject track id;
7. portable-identity authority.

The SHA-256 of that canonical material is truncated to 24 lowercase hex characters and prefixed with `bodyid-`.

Consequences:

- renaming or moving unchanged source files does not change the body id;
- changing caller/source order does not change the body id;
- changing the operator alias does not change the body id;
- changing any source bytes, recovery evidence or visual-identity evidence changes the body id.

## Source-byte TOCTOU boundary

A clone must not recover one set of bytes and later assign identity from different bytes at the same paths.

`clone-body.ps1` therefore:

1. hashes every resolved source file immediately before recovery;
2. builds an order-independent aggregate source-set SHA-256 from the sorted individual file digests;
3. runs recovery and visual-identity capture;
4. asks `bodyrig.portable_identity` to recompute the source-set digest;
5. fails closed if the digest changed before the create-only receipt is committed.

Paths are used only to read local build inputs. They are not incorporated into portable identity material.

## Evidence re-binding

The receipt is not trusted merely because its syntax and body id are self-consistent.

Before the external fitter uses its canonical body id, `external_fitter_cli.py` re-binds the receipt to the exact:

- recovery proof;
- visual identity bound to that proof;
- source count;
- subject track;
- requested operator alias.

Gate A performs the same proof/visual/alias re-binding from persistent evidence after private source media/workspaces may already have been cleaned up. Gate A intentionally cannot recompute the source-set digest at that stage; the source-byte binding was established create-only during the clone.

## Package and provenance

During the clone, the output `.mrbody` file may keep the operator alias in its local filename so the physical session can find its artifact. Its **manifest id** is the canonical `bodyid-*`.

The package provenance must contain exactly one identity stage:

```text
stage    = identity_content
adapter  = bodyrig.portable_identity
revision = <24 hex characters from canonical bodyid>
```

Gate A verifies that stage and then promotes the accepted package under canonical `<bodyid>.mrbody`. The portable-identity receipt is copied byte-exact into the Gate A acceptance bundle.

## Validation rules

Portable identity is fail-closed:

- exact v1 field set only;
- `version` must be the integer `1` — JSON boolean `true` is not accepted as Python-equivalent `1`;
- lowercase canonical SHA-256 strings only;
- canonical `bodyid-*` must recompute from receipt contents;
- duplicate JSON keys and non-finite constants are rejected;
- create-only receipt output may not overwrite existing evidence;
- receipt/evidence mismatch prevents fitting or Gate A promotion.

## Trust boundary

Portable identity is a deterministic package/runtime identity authority, not a claim of biometric identity or perfect physical likeness. Human source-identity, texture, geometry and deformation quality remain physical acceptance gates on WindowsPlayer and Quest-class hardware.
