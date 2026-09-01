# Donor-topology fidelity plan

The physical renderer proved that source-shell face deletion removes membrane fans but exposes holes. The next architecture must preserve a closed, stable body surface.

Plan:
1. Use fitted SMPL-X donor topology as body geometry authority.
2. Transfer source appearance onto donor geometry instead of retaining the raw reconstructed source faces.
3. Keep source-derived local detail bounded and measured; do not let raw reconstruction define cross-body connectivity.
4. Run mesh-topology QA before acceptance.
5. Keep face reconstruction as a separate blocker and do not hide facial failure behind smoothing.

Success criteria for the body stage:
- no long/sliver bridge candidates;
- closed underarm surface in front/three-quarter/side renders;
- substantially smoother body surface than the raw source shell;
- body silhouette remains source-proportion plausible;
- no production activation without human visual review.
