# Recovery throughput candidate

This branch is a performance candidate only. It must not become physical authority from CI alone.

## Change

Selected observation segments keep their full selected time window and original spatial resolution. FFmpeg applies an output frame-rate expression equivalent to `min(15, source_fps)` before the shared recovery/identity pipeline consumes them.

The goal is to reduce redundant PHALP/HMR2 frame work without ever manufacturing extra frames from low-frame-rate source media. On 30 fps source material the recovery frame count is expected to be roughly halved; on 60 fps material it can be reduced by roughly 75 percent. Sources already at or below 15 fps are not temporally upsampled by this candidate. Those are frame-count implications, not promised wall-clock speedups.

## Preserved boundaries

- Stash source selection and performer identity are unchanged.
- Observation quality/view selection is unchanged.
- Segment start time and duration are unchanged.
- Spatial resolution is not scaled by this change.
- Low-frame-rate sources are never intentionally upsampled by the throughput cap.
- Materialized segment bytes remain SHA-256 bound by the existing observation-segment manifest.
- Recovery proof, visual identity, portable identity, Gate A and physical release gates remain unchanged and fail closed.
- Built-in identity capture samples source media by timestamp at 0.75 second intervals, so a 15 fps ceiling still contains substantially denser temporal evidence than the identity sampler consumes.

## Required physical promotion evidence

Before this candidate may replace the current physical authority, run it against the same source/person class and compare with the uncapped baseline:

1. all selected segments complete PHALP/HMR2 recovery;
2. recovery proof remains valid with adequate observed frames and source coverage;
3. identity capture succeeds and its coverage/quality evidence does not regress materially;
4. high-fidelity fitter and Gate A remain green;
5. canonical fidelity review images show no material identity/geometry/texture regression;
6. record elapsed recovery time and per-segment frame counts for baseline versus candidate.

CI proves the command/provenance contract, not visual equivalence or physical throughput.
