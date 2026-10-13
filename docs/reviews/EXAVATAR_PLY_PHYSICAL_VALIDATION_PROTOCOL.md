# ExAvatar PLY compatibility and benchmark protocol

**Status:** Operator-ready protocol only. No physical-rig measurement has been made by this document. V1 `main` remains frozen; no training or production authorization.

## Preconditions

1. Use the current tested integration checkout from PR #1374, and verify its exact HEAD has completed all required CI checks before running. Record `git rev-parse HEAD` and ensure `git status --porcelain` is empty. Do not assume the older `71afbbeee` commit is the latest tested head.
2. Keep input meshes read-only and outside the repository. Do not upload private meshes, images, or absolute dataset paths to GitHub.
3. Pick a small, representative set of upstream **ASCII, binary little-endian, and binary big-endian** PLY files if each format actually exists in upstream exports. Record which formats are absent rather than manufacturing coverage.
4. Ensure every compared baseline/candidate run uses the **same input files**, Python runtime, environment, and host; run sequentially, with no concurrent training or GPU load. This is a diagnostic CPU/parser comparison, not a GPU throughput test.

## Compatibility evidence

For each real mesh, record: format; vertex count; declared vertex property types and ordering; whether x/y/z are present; read success/failure; number of finite projected points; any dropped non-finite coordinates; and whether a known independent reader agrees on vertex count and bounding extents. Capture a redacted error message on failure. Do not claim the test matrix covers formats not present in the actual export set.

The parser intentionally yields non-finite values and the projection layer filters them. Count and report these exclusions; **do not** reinterpret a successful parse as a valid 3D fit or silently convert all-invalid meshes into success.

## Reproducible performance comparison

Use two separate, clean worktrees/checkouts: the unmodified `main` baseline at its recorded SHA and the integration commit above. The parser may change behavior on malformed inputs; compare timing only for identical successfully parsed meshes, and separately report any change in acceptance/rejection.

Example operator harness (run in each checkout with the same mesh argument; use a path outside the repo for output):

```python
# Save outside the repository as exavatar_ply_benchmark.py
import json
import resource
import statistics
import sys
import time
from pathlib import Path

from bodyrig.photoreal_exavatar_fit_diagnostic import _vertices

mesh = Path(sys.argv[1])
samples = []
count = None
for _ in range(5):
    started = time.perf_counter()
    current = sum(1 for _ in _vertices(mesh))
    samples.append(time.perf_counter() - started)
    if count is not None and count != current:
        raise RuntimeError("Non-deterministic vertex count")
    count = current
print(json.dumps({
    "mesh": mesh.name,
    "vertices": count,
    "seconds": samples,
    "median_seconds": statistics.median(samples),
    "peak_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
}))
```

Run `python3 /path/to/exavatar_ply_benchmark.py /path/to/mesh.ply` from each checkout, ensuring its module import resolves to that checkout. The `peak_rss_raw` field is platform-dependent (typically KiB on Linux, bytes on macOS), process-level, and includes Python interpreter overhead; **do not** compare across OSes or label it MiB without conversion. Run independent processes for each repetition if collecting per-run peak RSS. This example is for Linux/macOS Python because `resource` is unavailable in native Windows Python; run under WSL/Linux for the planned comparison. The script measures **parser throughput**, not end-to-end projection, robust bounding box, or full pipeline memory.

## Decision table

| Gate | Evidence required | Current status |
| --- | --- | --- |
| Synthetic integration | CI on combined parser and tests | PASS at `1cb0cf7c` (verify the current HEAD before execution) |
| Real-export PLY compatibility | Actual upstream exports with independent cross-check | NOT RUN |
| Parser performance | Matched baseline/candidate timing and RSS with raw measurements | NOT RUN |
| Camera-space convention | Physical rig and verified transforms | NOT RUN |
| Held-out human visual fit | Independent human review | NOT RUN |
| Teacher training / production | All mandatory gates approved | NO-GO |

No merge or production approval is implied by this protocol.
