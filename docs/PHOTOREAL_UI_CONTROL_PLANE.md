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

The start `launch.json` is itself treated as authority, not loose metadata. Drift accepts it only when format/version, category directory, canonical launch id, positive PID, start timestamp and context all validate. Restart-safe supervisor receipts additionally require canonical in-directory request/log/result paths and a request artifact whose SHA-256 still matches the receipt. The request artifact's launch id, category, start timestamp and context must also match the start receipt, so a rehashed but semantically different request is rejected. Symlinked or moved receipt paths are rejected. Invalid start receipts are surfaced as explicit `unknown` integrity failures and are prioritized in the bounded launch history instead of being silently skipped.

While the PowerShell child is active, the supervisor atomically refreshes a hash-bound `heartbeat.json` every two seconds. For restart-safe supervisor launches, Drift reports `running` only when the launch receipt, request SHA-256, fresh heartbeat and live supervisor PID all agree. PID existence alone is never running authority, so PID reuse after a restart cannot create a false active launch. Heartbeat write failures do not abort the supervised child; they only make the read side fail closed to `unknown` until a fresh heartbeat or terminal result appears.

Drift can therefore distinguish `running`, `succeeded`, `failed` and terminal-without-result/`unknown`, with exit code, finish time and duration when available. New terminal receipts are accepted only when launch id, supervisor PID and request SHA-256 match the start authority and the state agrees with the exit code. The actual PowerShell child PID is recorded as diagnostic metadata when available.

If the supervisor itself is killed or cannot persist a result, Drift remains fail-closed and reports the launch as unknown; it never infers PASS merely because a PID disappeared or was reused. Older launch receipts created before the supervisor model remain readable under the previous launch-id/PID checks.

### Persisted UI jobs

Drift treats persisted BodyRig jobs as first-class operational state. It counts the complete backend open-state set (`uploading`, `queued`, `running`, `needs_speaker`, `needs_reference`, `cancelling`) rather than only queued/running work, and explicitly calls out jobs that require operator input.

For each recent job the UI surfaces the persisted stage, evidence-backed progress when available, message/error text, bounded diagnostic tail, PID and timestamps. Body-build progress marked `pipeline-phase-estimate-v1` is shown as a phase estimate, never as a wall-clock ETA. Cancellation controls mirror backend authority: queued physical body builds can be cancelled before subprocess start; running physical builds remain fail-closed because WSL/child termination cannot be proven; open VoiceRig jobs use the existing typed cancel endpoint.

Open VoiceRig jobs are re-read through the existing authoritative per-job endpoint before Drift renders them, so remote transitions such as `running → needs_speaker` or `needs_reference` do not depend on another Person Studio tab being open. When VoiceRig requires disambiguation, Drift renders the exact returned speaker/reference choices, including browser audio previews when supplied, and submits only the existing typed `/speaker?anchor=...` or `/reference?choice=...` actions. Missing or malformed choice evidence remains fail-closed: Drift never invents or auto-selects a fallback. A failed authoritative VoiceRig refresh is surfaced as a monitoring error, clears any persisted choice payload from the Drift view, blocks disambiguation controls, and makes the Jobs area require attention.


Drift job history is filterable locally by selected person, build kind, operational state and free-text identifiers/stages/revisions without changing backend job authority or issuing extra mutation calls. The rendered history remains bounded to the newest 30 matching rows. Each row has an expandable, whitelisted evidence view for stable provenance and revision/hash fields rather than dumping the raw persisted job object. A job can navigate back to its exact Person Studio profile and relevant Body/Voice tab through the existing sidebar selection path; navigation adds no API or execution authority.

If either the persisted-job feed or operator-launch feed cannot be read, the Drift top summary reports that monitoring gap instead of declaring the system green.

Drift health and monitoring reads are timeout-bounded and fetched with `no-store`. Service health requires the expected readiness evidence for each integration, not merely a successful HTTP response: BodyRig physical-build authority, operator checkout authority, Stash performer-read, exact ModelRig/VoiceRig service identity, a structurally valid runtime snapshot, and WSL/CUDA plus PowerShell readiness. Each service card shows when the current read was confirmed and retains the last confirmed timestamp across a transient failure. Evidence older than the freshness window is not green authority. Stale system-readiness never leaves environment action buttons enabled. The same bounded read path is used for persisted jobs, authoritative open VoiceRig job refreshes, operator-launch history, Person lookup and the read-only Photoreal mirror so one hanging monitor cannot indefinitely preserve an old green control-plane view.

The UI persists only service observation timestamps (`last_attempt`, `last_confirmed`, `last_green`) in browser local storage under a versioned schema with a seven-day retention limit. No health payloads, credentials, service data or command authority are persisted. Restored timestamps are contextual history only: current green/stale authority still depends exclusively on a fresh current-session `observed_ms` result. This lets Drift show “sidst grøn” after a page reload without allowing historical evidence to revive a stale green service state.

The Drift top summary also reflects unresolved operational outcomes. It flags jobs waiting for operator input and the latest failed/interrupted job for each person/kind. Operator launches are evaluated latest-first per category plus gate/action, so a later successful or running retry supersedes an older failure. Historical failures therefore remain visible in the detailed lists without keeping the whole control plane permanently red.

### Drift mirror

Person Studio Drift mirrors the selected person's Photoreal V2 control-plane as read-only operational state. It shows the current pipeline state/next gate together with ExAvatar phase, workspace, preprocess progress, checkpoint evidence, neutral renders, active-process count and latest-log timestamp.

The Drift mirror never exposes the Photoreal action endpoint and does not duplicate execution authority. Canonical advance actions remain on the Body/Photoreal control card. A person with no Photoreal run, or without a Stash performer binding, is neutral/inactive. An active ExAvatar process is shown as running. When no process is busy, required, human-review-required, operator-input-required, blocked or unreadable Photoreal state contributes to the top-level Drift attention summary.


The same read-only mirror now includes a bounded history of recent performer-bound Photoreal P0 runs. Candidate discovery reuses the artifact performer declarations and ignores symlinked/non-matching runs. Exactly the latest valid run used by the control-plane status is marked as the continuation candidate; older runs are explicitly history-only and never gain execution authority. History shows only stable local evidence such as P0 status presence, calibration integrity/authorization state, teacher-root/input/config/manifest presence and a performer-bound teacher-input SHA-256 when valid. Historical entries never expose a next command or action endpoint.

