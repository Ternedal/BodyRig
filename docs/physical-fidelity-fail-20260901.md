# Physical fidelity fail — 2026-09-01

Observed topology-repaired package: `3e7f5dc8c73d3cf3052c6757a65a95bf662a4b36d6712bd452e2ed4e1355b702` (derived from source package `8a8915658201eb8a391a3a2771b2e36bc4fe0e20d293259e015938d5aa6f1897`).

Human visual review result: FAIL.

Findings:
- Long/sliver membrane triangles were removed successfully by the diagnostic topology repair.
- Their removal exposed open underarm geometry and visible holes; face deletion is therefore not a production repair.
- Face geometry remained collapsed/faceted and visually unchanged.
- Body surface remained strongly rippled/faceted.

Conclusion:
- Keep topology QA as a fail-closed diagnostic/gate.
- Do not ship face-deletion as the geometry repair strategy.
- Rework the fitter so fitted SMPL-X donor topology is the stable body geometry authority; source reconstruction should contribute appearance/texture and bounded local detail rather than define the complete render topology.
- Treat facial reconstruction as a separate blocker after the body-topology rework.
