# ExAvatar PR #1372 – independent review (2026-10-12)

Scope: static review of the PR patch, not a rig execution or photoreal acceptance. V1 main remains frozen.

## Confirmed observations

- `_robust_bbox` sorts its input twice in place. Its returned quantiles match the former independent sorted-coordinate implementation, but the caller must own the mutable list. Current `_mesh_projection` constructs `projected` locally.
- `_indexed_frames` uses a set for duplicate detection and preserves file order in the returned tuple.
- PLY header and ASCII vertex line reads are bounded, improving resilience against oversized inputs.
- The added tests cover header length, non-ASCII header, duplicate property names, invalid vertex count, long ASCII vertex rows, quantile equivalence, frame ordering, and short PNG header.

## Follow-up review gates (not yet proven)

1. Verify representative real-world ASCII, little-endian binary, and big-endian binary PLY meshes; synthetic fixtures alone do not establish upstream compatibility.
2. Validate that malformed binary PLY coordinates and non-finite ASCII coordinates have explicit documented policy. Current projection deliberately filters non-finite vertices, rather than failing the whole mesh; do not change this without reviewing legitimate partially invalid meshes and the acceptance boundary.
3. Check `_vertices` handling of malformed headers and missing/invalid property declarations against representative upstream exports.
4. Run a baseline-vs-candidate performance benchmark on the physical rig with identical meshes and collect wall time, peak RSS, and projection results. No speedup is claimed without measurements.
5. Keep camera-space convention and human visual-fit acceptance as independent NO-GO gates; diagnostics cannot authorize teacher training or production activation.

## Disposition

REVIEW PENDING. Do not merge on this review alone. No training, runtime authority, release gate, or production flag changes.
