# ExAvatar combined integration CI evidence — 2026-10-13

## Scope and provenance

- Integration PR: #1374 (draft), base: `work/photoreal-v2-readonly-preflight-20261011` (PR #1372).
- Integration commit: `31939edf92a390036a80028f395ca81b4a55887f`.
- Added synthetic regression suite: `tests/test_exavatar_ply_compatibility_review.py`.
- GitHub Actions CI run: `38313634602` — completed successfully.
- CI jobs: `test (3.11)`, `test (3.12)`, `test-windows-python`, `acceptance-windows` — all completed successfully.
- Other successful runs: CodeQL `38313634660`, LOC metrics `38313634611`, Windows log-handle regression `38313634595`.

## What this proves

The test suite passes on the combined branch that contains PR #1372's hardened PLY parser plus synthetic ASCII, little-endian, big-endian, nonfinite-coordinate and truncated-record compatibility tests. The checks are automated and do not use the physical rig.

## What remains unproven

- Compatibility with representative real upstream PLY exports.
- Physical-rig wall-time and peak-memory benchmarks against the baseline on identical data.
- Camera-space convention, held-out human visual-fit assessment, and actual performer acceptance.
- Production training authorization: **NO-GO**.

## Integration disposition

CI PASS; physical acceptance NOT RUN; photoreal release authority NOT GRANTED. Keep PR #1372 and #1374 draft and preserve V1 main freeze. This document does not grant merge approval.
