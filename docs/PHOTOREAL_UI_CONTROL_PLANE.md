# BodyRig UI control-plane direction

Person Studio is the normal operator surface for BodyRig.

The UI should expose the current state and safe continuation of the major BodyRig pipelines instead of requiring the operator to reconstruct state from PowerShell output. CLI and PowerShell remain the canonical authority/recovery layer underneath the UI; the browser never becomes shell authority.

## Photoreal V2 / ExAvatar

The Body tab contains a Photoreal V2 control plane that:

- reads the existing canonical P0 -> P3 status engine;
- shows P0, static-teacher/P1, animated/P2 and device/P3 gates;
- probes the configured ExAvatar WSL workspace read-only for completed preprocess stages, checkpoints, neutral renders, active processes and the latest log tail;
- polls more frequently while ExAvatar is active;
- surfaces explicit missing operator inputs instead of guessing them;
- launches only the exact `next_command` recomputed by the canonical backend status engine;
- refuses a competing launch while ExAvatar appears active;
- never turns human review, photoreal acceptance or production authority into an automatic UI action.

The same pattern is the target for the remaining BodyRig operator workflows: status first, explicit inputs, canonical backend action, persisted evidence, and fail-closed continuation.


## Drift / operator launches

The Drift tab is also the lifecycle view for UI-started canonical operator processes.

Each launch keeps its immutable start receipt and log, and BodyRig now records a separate terminal result receipt when the exact child process exits. Drift can therefore distinguish `running`, `succeeded`, `failed` and terminal-without-result/`unknown`, with exit code, finish time and duration when available. A terminal receipt is accepted only when its launch id and PID match the start receipt and its state agrees with the exit code.

If BodyRig itself stops before the watcher can persist a terminal receipt, the UI remains fail-closed and reports the launch as unknown; it never infers PASS merely because a PID disappeared or was reused.
