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

### Person Overview operator triage

The Person Overview cockpit stays read-only but now includes a person-scoped operator-attention layer above its generic Source → Body → Voice → Personality → Person Revision → Digital Twin guide. It reads only existing GET surfaces: the selected Person profile, person-filtered persisted UI jobs, authoritative per-job VoiceRig detail for open voice jobs, the Photoreal control-plane status when the Person has a Stash performer binding, and Digital Twin M1–M6 readiness.

Explicit operator input or a current monitoring blocker may supersede the generic “next pipeline stage” card: VoiceRig speaker/reference selection, unreadable VoiceRig state, suspected ExAvatar stall, idle Photoreal blocked/input/review state, or unreadable Digital Twin status. A healthy active ExAvatar process is not treated as operator input merely because a future gate is already known. The latest failed/interrupted body/voice job remains visible as lower-priority context but cannot by itself override normal pipeline guidance.

The Overview renders only bounded text summaries and navigates to the existing Body, Voice or Drift tabs. It contains no POST, no action endpoint, no shell/command transport, no human-review recorder and no production-activation acknowledgement. Canonical action authority remains in the existing component/control-plane surfaces.


## Drift / operator launches

The Drift tab is also the lifecycle view for UI-started canonical operator processes.

Each launch keeps its immutable start receipt and log. BodyRig writes a hash-bound `request.json` and starts a separate restart-safe supervisor process, which launches the exact canonical PowerShell command with `shell=False`, waits for that child, and atomically records a terminal `result.json`. The supervisor is detached from the BodyRig process/session, so a normal BodyRig restart does not destroy terminal-status ownership.

The start `launch.json` is itself treated as authority, not loose metadata. Drift accepts it only when format/version, category directory, canonical launch id, positive PID, start timestamp and context all validate. Restart-safe supervisor receipts additionally require canonical in-directory request/log/result paths and a request artifact whose SHA-256 still matches the receipt. The request artifact's launch id, category, start timestamp and context must also match the start receipt, so a rehashed but semantically different request is rejected. Symlinked or moved receipt paths are rejected. Invalid start receipts are surfaced as explicit `unknown` integrity failures and are prioritized in the bounded launch history instead of being silently skipped.

While the PowerShell child is active, the supervisor atomically refreshes a hash-bound `heartbeat.json` every two seconds. For restart-safe supervisor launches, Drift reports `running` only when the launch receipt, request SHA-256, fresh heartbeat and live supervisor PID all agree. PID existence alone is never running authority, so PID reuse after a restart cannot create a false active launch. Heartbeat write failures do not abort the supervised child; they only make the read side fail closed to `unknown` until a fresh heartbeat or terminal result appears.

Drift can therefore distinguish `running`, `succeeded`, `failed` and terminal-without-result/`unknown`, with exit code, finish time and duration when available. New terminal receipts are accepted only when launch id, supervisor PID and request SHA-256 match the start authority and the state agrees with the exit code. The actual PowerShell child PID is recorded as diagnostic metadata when available.


The operator-launch view is filterable locally by selected Person, canonical launch category, terminal/running state and free-text launch/context identifiers. Drift fetches at most 50 launch receipts and renders at most the first 30 matching entries, preserving backend integrity-failure priority. Each row exposes a whitelisted evidence panel for launch/category/state, typed context identifiers, PIDs, heartbeat/result timestamps, duration/exit and receipt integrity; raw receipt/request objects are never dumped into the browser. Log tails are collapsed by default. Launches carrying a `context.person_id` can navigate back to that Person's Body tab through the existing Person Studio selection path; this navigation adds no execution authority.

If the supervisor itself is killed or cannot persist a result, Drift remains fail-closed and reports the launch as unknown; it never infers PASS merely because a PID disappeared or was reused. Older launch receipts created before the supervisor model remain readable under the previous launch-id/PID checks.

### Persisted UI jobs

Drift treats persisted BodyRig jobs as first-class operational state. It counts the complete backend open-state set (`uploading`, `queued`, `running`, `needs_speaker`, `needs_reference`, `cancelling`) rather than only queued/running work, and explicitly calls out jobs that require operator input.

For each recent job the UI surfaces the persisted stage, evidence-backed progress when available, message/error text, bounded diagnostic tail, PID and timestamps. Body-build progress marked `pipeline-phase-estimate-v1` is shown as a phase estimate, never as a wall-clock ETA. Cancellation controls mirror backend authority: queued physical body builds can be cancelled before subprocess start; running physical builds remain fail-closed because WSL/child termination cannot be proven; open VoiceRig jobs use the existing typed cancel endpoint.

Open VoiceRig jobs are re-read through the existing authoritative per-job endpoint before Drift renders them, so remote transitions such as `running → needs_speaker` or `needs_reference` do not depend on another Person Studio tab being open. When VoiceRig requires disambiguation, Drift renders the exact returned speaker/reference choices, including browser audio previews when supplied, and submits only the existing typed `/speaker?anchor=...` or `/reference?choice=...` actions. Missing or malformed choice evidence remains fail-closed: Drift never invents or auto-selects a fallback. A failed authoritative VoiceRig refresh is surfaced as a monitoring error, clears any persisted choice payload from the Drift view, blocks disambiguation controls, and makes the Jobs area require attention.


Drift job history is filterable locally by selected person, build kind, operational state and free-text identifiers/stages/revisions without changing backend job authority or issuing extra mutation calls. The rendered history remains bounded to the newest 30 matching rows. Each row has an expandable, whitelisted evidence view for stable provenance and revision/hash fields rather than dumping the raw persisted job object. A job can navigate back to its exact Person Studio profile and relevant Body/Voice tab through the existing sidebar selection path; navigation adds no API or execution authority.

If either the persisted-job feed or operator-launch feed cannot be read, the Drift top summary reports that monitoring gap instead of declaring the system green.

Drift health and monitoring reads are timeout-bounded and fetched with `no-store`. Service health requires the expected readiness evidence for each integration, not merely a successful HTTP response: BodyRig physical-build authority, operator checkout authority, Stash performer-read, exact ModelRig/VoiceRig service identity, a structurally valid runtime snapshot, and WSL/CUDA plus PowerShell readiness. Each service card shows when the current read was confirmed and retains the last confirmed timestamp across a transient failure. Evidence older than the freshness window is not green authority. Stale system-readiness never leaves environment action buttons enabled. The same bounded read path is used for persisted jobs, authoritative open VoiceRig job refreshes, operator-launch history, Person lookup and the read-only Photoreal mirror so one hanging monitor cannot indefinitely preserve an old green control-plane view.


Blocked/offline/stale service cards expose their reasons separately under a **Hvorfor?** section instead of burying blockers inside the summary line. System-readiness supplies its blocker list from the backend so missing PowerShell 7, WSL availability, NVIDIA visibility, exact CUDA 12.4, ExAvatar runtime Python/receipt, Photoreal materializer runtime and pinned public dependency receipt are individually identifiable. Quest connectivity stays advisory at global system-readiness level; Quest-specific preflight still enforces it when requested. A stale read adds freshness as its own blocker, and a failed monitor read includes the last-confirmed age when available.

The same **Hvorfor?** pattern now covers the person-scoped Photoreal/ExAvatar and Digital Twin M1–M6 cards. Photoreal explanations are derived only from the current strict pipeline message/next gate, bounded missing-operator-input names, ExAvatar monitor reason and liveness stall evidence. Busy/current work without a stall does not become a false blocker. Digital Twin explanations are derived from the strict top-level message/next gate, unresolved milestone messages and bounded M5 blocker strings. These explanatory panels are render-only and never expose `next_command`, raw shell transport, additional mutation endpoints, or new review/activation authority.

The UI persists only bounded service observation metadata in browser local storage under a versioned schema with a seven-day retention limit. Per-service `last_attempt`, `last_confirmed` and `last_green` timestamps are retained together with at most 120 state-transition events containing only service id, `green|blocked|offline` and observation timestamp. Consecutive polls in the same state do not create duplicate timeline events. No health payloads, blocker/error text, credentials, service data or command authority are persisted. The v2 store can read the previous timestamp-only v1 store and migrates naturally on the next observation.

Restored timestamps and transitions are contextual history only: current green/stale authority still depends exclusively on a fresh current-session `observed_ms` result. Drift renders at most the latest 40 transitions in a collapsed browser-local health timeline, making flapping and recovery visible without allowing historical evidence to revive a stale green service state or enable any action.

The Drift top summary also reflects unresolved operational outcomes. It flags jobs waiting for operator input and the latest failed/interrupted job for each person/kind. Operator launches are evaluated latest-first per category plus gate/action, so a later successful or running retry supersedes an older failure. Historical failures therefore remain visible in the detailed lists without keeping the whole control plane permanently red.

### Drift mirror

Person Studio Drift mirrors the selected person's Photoreal V2 control-plane as read-only operational state. It shows the current pipeline state/next gate together with ExAvatar phase, workspace, preprocess progress, checkpoint evidence, neutral renders, active-process count and latest-log timestamp.

The Drift mirror never exposes the Photoreal action endpoint and does not duplicate execution authority. Canonical advance actions remain on the Body/Photoreal control card. A person with no Photoreal run, or without a Stash performer binding, is neutral/inactive. An active ExAvatar process remains execution-busy and therefore still blocks competing continuation.

ExAvatar liveness is evaluated separately from that busy lock. The read-only WSL probe records the age of matching workspace-bound ExAvatar processes and the latest canonical preprocess/teacher log. A matching process is marked `stalled-suspected` only when activity evidence is stale for more than 30 minutes. Known process age takes precedence over an older log from a previous stage: a process younger than 30 minutes is never called stalled solely because the previous-stage log is old. When no log exists, the warning is raised only after the oldest matching process itself is older than 30 minutes. Suspected stall raises Drift top-level attention and is shown on both Drift and the Body/Photoreal card, but it never kills, restarts, or supersedes the process, never clears `busy`, and never enables a competing canonical advance.


Drift also exposes the current ExAvatar workspace's bounded live diagnostics under a collapsed read-only section. It reuses the same control-plane payload rather than issuing a second WSL probe: at most 20 matching workspace-bound process descriptions are rendered, each already bounded to 1200 characters by the backend, together with the latest preprocess/teacher log tail bounded to the final 20 lines and 6000 characters. Rendering uses text content only. The diagnostics section has no action endpoint, process termination capability, restart control or shell transport; it exists only to make suspected stalls and long-running stages diagnosable without leaving Person Studio.


The same read-only mirror now includes a bounded history of recent performer-bound Photoreal P0 runs. Candidate discovery reuses the artifact performer declarations and ignores symlinked/non-matching runs. Performer identity declarations themselves must be regular non-symlink files; an external symlink target can never establish run identity. Filesystem races are fail-closed: a run that disappears between discovery and history read is skipped instead of failing the whole Drift status. Exactly the latest valid run used by the control-plane status is marked as the continuation candidate; older runs are explicitly history-only and never gain execution authority. History shows stable local evidence such as P0 status presence, calibration integrity/authorization state, teacher-root/input/config/manifest presence and a performer-bound teacher-input SHA-256 when valid.

For the current continuation candidate only, the history row reuses the already-computed live ExAvatar evidence from the main control-plane probe: the exact resolved teacher root/workspace, phase, preprocessing counts, highest checkpoint, neutral-render count and latest-log name/timestamp. It does not run a second WSL probe, and historical rows remain local evidence only. If the status engine resolves a non-default teacher-work root, the history row preserves that exact root instead of reconstructing one from the P0 directory. Historical entries never expose a next command, action button or action endpoint.

### Digital twin M1–M6 mirror

Drift also exposes a read-only M1–M6 status for the selected Person. The monitor is scoped to the active approved Person Revision and never creates or mutates release evidence.

The read side resolves the exact audition-bound Person assembly receipt and active body revision, reuses the canonical body release status for M1, strict-reads finalized hands/feet/nails and wardrobe authorities for M2/M3, and strict-reads the create-only M4 composition authority. Before M4 exists, multiple valid M2/M3 authorities are treated as ambiguous. Once one exact M4 authority exists, its frozen M2/M3 bindings resolve that historical ambiguity because M4 has already revalidated and frozen the selected component lineage.

M5/M6 are evaluated only when the active M4 authority can be bound to one exact succeeded BodyRig body-build acceptance directory with matching Person, body revision, canonical body id and BodyRig revision. Drift then delegates to the existing read-only `digital_twin_operator_status` engine. The public Drift payload strips every raw `next_command`, including nested M5 platform commands; only milestone state, messages, whitelisted platform evidence and final readiness booleans cross the browser boundary.

Only strict M6 readback may show `digital_twin_ready=true` and `production_activation=true`. Missing, invalid or ambiguous evidence remains required/blocked. Drift exposes command-free typed actions for the machine-executable M5 realization gates and, only after M1–M5 are strict-complete, the canonical M6 final release. The browser never receives the canonical command.

`advance-m5` backend-recomputes the complete current M4 → physical acceptance → M5 status and launches only when the gate is still `digital_twin_platform_acceptance` and the platform is one of the two canonical M5 targets. `finalize-m6` is separate and requires an explicit `confirm_production_activation=true` acknowledgement from the UI after a production warning. The backend then strict-recomputes the full current lineage again and launches only when the exact operator-status gate remains `digital_twin_final_release`, M5 is still ready, M6 is still eligible, no M6 authority exists yet, and an exact expected release id plus canonical command are available from the clean evidence checkout. The action response remains `production_activation=false` and `strict_readback_required=true`; only a subsequent strict M6 readback may declare production active. Drift never auto-records human or physical PASS.


For M2 and M3, Drift additionally exposes read-only substage evidence beneath the six-milestone summary. Each component is split into **source capture → render + human review → finalized authority**. The source/review stages reuse the existing strict hands/feet/nails and wardrobe readers against the active Person/body lineage; finalized state remains the same strict M2/M3 milestone authority used by the digital-twin chain. The monitor exposes only state, bounded counts and canonical evidence/authority ids — never source media paths, captured images, quality notes, raw receipts or shell commands.

Candidate scans are deliberately bounded to eight canonical non-symlink directories per evidence type on each refresh. If more exist, the payload marks the scan as bounded instead of pretending the complete historical set was revalidated. Invalid candidates count as rejected strict readbacks; a directory read race fails closed as blocked monitoring evidence. M2/M3 substages remain observational only: Drift still cannot create captures, record human review, finalize M2/M3 or choose ambiguous authorities. The typed M5 action cannot cross those gates.


For M4–M6, Drift now mirrors the downstream strict realization chain as separate read-only substages: **M4 composition → exact physical acceptance**, **M5 Windows → Quest → finalized realization**, and **M6 canonical release**. M4 physical acceptance is not marked complete merely because an acceptance directory exists; completion requires the existing downstream digital-twin operator status to validate that exact M4-bound acceptance chain. Windows and Quest states are taken only from the already-sanitized strict M5 platform status, and M6 remains the same strict canonical release milestone.

This downstream pane exposes only state, canonical authority ids, already-whitelisted evidence directories, messages and a command-free typed action catalog. The action endpoint can launch the next canonical Windows/Quest M5 machine probe and the explicitly confirmed canonical M6 finalizer through the restart-safe operator supervisor. It still has no platform attestation capability and no human/physical PASS authority. A gate change between render and click is strict-revalidated and rejected. Missing platform status or a failed downstream strict read stays blocked instead of being inferred from file presence.

M5 and M6 launches are persisted under the `digital-twin` operator-launch category. M6 context records the exact Person/revision, M4 authority, expected canonical M6 release id and `production_activation_requested=true` for audit. That launch record is not release authority; terminal success still does not make Drift green until the canonical M6 authority is strict-read back and reports both `digital_twin_ready=true` and `production_activation=true`.

