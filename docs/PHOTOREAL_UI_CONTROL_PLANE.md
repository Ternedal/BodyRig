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

Each launch keeps its immutable start receipt and log. BodyRig writes a hash-bound `request.json` and starts a separate restart-safe supervisor process, which launches the exact canonical PowerShell command with `shell=False`, waits for that child, and atomically records a terminal `result.json`. The supervisor is detached from the BodyRig process/session, so a normal BodyRig restart does not destroy terminal-status ownership.

Drift can therefore distinguish `running`, `succeeded`, `failed` and terminal-without-result/`unknown`, with exit code, finish time and duration when available. New terminal receipts are accepted only when launch id, supervisor PID and request SHA-256 match the start authority and the state agrees with the exit code. The actual PowerShell child PID is recorded as diagnostic metadata when available.

If the supervisor itself is killed or cannot persist a result, Drift remains fail-closed and reports the launch as unknown; it never infers PASS merely because a PID disappeared or was reused. Older launch receipts created before the supervisor model remain readable under the previous launch-id/PID checks.

### Persisted UI jobs

Drift treats persisted BodyRig jobs as first-class operational state. It counts the complete backend open-state set (`uploading`, `queued`, `running`, `needs_speaker`, `needs_reference`, `cancelling`) rather than only queued/running work, and explicitly calls out jobs that require operator input.

For each recent job the UI surfaces the persisted stage, evidence-backed progress when available, message/error text, bounded diagnostic tail, PID and timestamps. Body-build progress marked `pipeline-phase-estimate-v1` is shown as a phase estimate, never as a wall-clock ETA. Cancellation controls mirror backend authority: queued physical body builds can be cancelled before subprocess start; running physical builds remain fail-closed because WSL/child termination cannot be proven; open VoiceRig jobs use the existing typed cancel endpoint.

If either the persisted-job feed or operator-launch feed cannot be read, the Drift top summary reports that monitoring gap instead of declaring the system green.

The Drift top summary also reflects unresolved operational outcomes. It flags jobs waiting for operator input and the latest failed/interrupted job for each person/kind. Operator launches are evaluated latest-first per category plus gate/action, so a later successful or running retry supersedes an older failure. Historical failures therefore remain visible in the detailed lists without keeping the whole control plane permanently red.

### Drift mirror

Person Studio Drift mirrors the selected person's Photoreal V2 control-plane as read-only operational state. It shows the current pipeline state/next gate together with ExAvatar phase, workspace, preprocess progress, checkpoint evidence, neutral renders, active-process count and latest-log timestamp.

The Drift mirror never exposes the Photoreal action endpoint and does not duplicate execution authority. Canonical advance actions remain on the Body/Photoreal control card. A person with no Photoreal run, or without a Stash performer binding, is neutral/inactive. An active ExAvatar process is shown as running. When no process is busy, required, human-review-required, operator-input-required, blocked or unreadable Photoreal state contributes to the top-level Drift attention summary.

