# Retained hair + eye preview

`run-retained-hair-eye-preview.ps1` is a comparison-only continuation for a completed retained SiTH identity workspace. It exists to answer one narrow physical question without paying for another reconstruction: do the source-derived hair and source-baked eye runtime materially improve the exact retained candidate in Windows/UniVRM?

The operator binds the input `.mrbody` package, retained `reconstruction.json`, reconstruction authority, source mesh, fitted donor OBJ, and fitted parameter JSON by SHA-256 before work starts and verifies those bytes again before publishing output. It runs source-hair extraction, explicit eye-geometry extraction, source-derived eye-appearance extraction, hair+eye review-runtime composition, and the existing Windows hair+eye preview. It never invokes Stash cloning or SiTH reconstruction.

The output remains deliberately non-authoritative. The summary records `reconstruction_rerun=false`, `comparison_only=true`, `full_fidelity_component_complete=false`, `human_review_required=true`, and `production_activation=false`. Iris appearance remains review-pending and eyelashes remain missing. The resulting images are therefore diagnostic physical preview evidence, not full-fidelity acceptance and not release authority.

Example using the retained workspace from a completed convergence reconstruction:

```powershell
.\run-retained-hair-eye-preview.ps1 `
  -PackagePath "$env:LOCALAPPDATA\BodyRig\fidelity-convergence\<run>\rebuild-01\clone-run\clone\<body>.mrbody" `
  -IdentityWorkspace "$env:LOCALAPPDATA\BodyRig\identity-workspaces\<retained-workspace>" `
  -OutputRoot "$env:LOCALAPPDATA\BodyRig\fidelity-convergence\<run>\retained-hair-eye-preview"
```

Inspect at minimum `windows-preview\snapshots\face-front.png`, `eyes-closeup.png`, `front-full.png`, and `three-quarter-full.png` before deciding whether component promotion or further composition work is justified.
