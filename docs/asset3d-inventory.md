# Local 3D asset inventory (experimental)

The fastest path requires **no provenance JSON or license form**. This is a
metadata-only inventory, not Blender inspection or production-ready rendering.

## Quick start (Windows PowerShell)

```powershell
python -m tools.asset3d_inventory C:\assets\staging --output C:\assets\manifest.json
python -m unittest discover -s tests -p test_asset3d_inventory.py -v
```

Optional provenance is a JSON object mapping relative asset paths to arbitrary
metadata. When present, pass it as the second positional argument. It is
informational and does not gate local inventory. Unknown metadata is reported
as `provenance_status: unknown`; no licensing conclusion is inferred.

The manifest includes content SHA-256, duplicate flags, dependency hashes,
`readiness: INVENTORIED` and `likeness_authority: false`. INVENTORIED does
**not** mean the asset is safe to render or available for image/video generation.

## Performance goals (not yet measured)

First usable asset <=120 seconds; cache reuse <2 seconds on the physical rig.
This inventory is only stage one. The next implementation needs progressive
readiness, content-addressed cache, isolated Blender inspection, stage timing,
and optional depth/normal/pose exports. Do not claim those are implemented.

## Security boundary

The static preflight checks local paths and selected glTF/OBJ dependencies,
but FBX/BLEND/GLB embedded references are not exhaustively inspected. OBJ/MTL
advanced texture syntax is rejected. Do not pass untrusted assets to Blender
until an isolated inspector with network isolation and resource limits exists.
Do not treat this manifest as identity evidence for BodyPrint, .mrbody or
Photoreal. Keep assets outside the repository.
