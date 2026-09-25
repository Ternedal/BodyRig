(() => {
  let timer = null;
  let serial = 0;
  let lastJobsPayload = null;
  let lastLaunchesPayload = null;
  const serviceObservations = new Map();

  const SERVICE_READ_TIMEOUT_MS = 7000;
  const SERVICE_STALE_MS = 25000;
  const SERVICE_OBSERVATION_STORAGE_KEY = "bodyrig-drift-service-observations-v1";
  const SERVICE_OBSERVATION_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

  const SERVICES = [
    ["bodyrig", "BodyRig", "/api/v1/health"],
    ["operator", "Operator checkout", "/api/v1/operator-authority"],
    ["stash", "Stash", "/api/v1/stash/health"],
    ["modelrig", "ModelRig", "/api/v1/modelrig/health"],
    ["voicerig", "VoiceRig", "/api/v1/voicerig/health"],
    ["runtime", "Runtime", "/api/v1/runtime/state"],
    ["system", "Rig / WSL / Quest", "/api/v1/operator/system-readiness"],
  ];
  const OPEN_JOB_STATES = new Set(["uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"]);
  const ACTION_JOB_STATES = new Set(["needs_speaker", "needs_reference"]);

  function persistedObservationStamp(value, now = Date.now()) {
    if (!Number.isFinite(value) || value <= 0) return null;
    if (value > now + 60000) return null;
    if (now - value > SERVICE_OBSERVATION_RETENTION_MS) return null;
    return value;
  }

  function restoreServiceObservations() {
    let raw = null;
    try {
      raw = window.localStorage.getItem(SERVICE_OBSERVATION_STORAGE_KEY);
    } catch {
      return;
    }
    if (!raw) return;

    let payload = null;
    try {
      payload = JSON.parse(raw);
    } catch {
      return;
    }
    if (
      !payload
      || typeof payload !== "object"
      || payload.format !== "bodyrig-drift-service-observations"
      || payload.version !== 1
      || !payload.services
      || typeof payload.services !== "object"
      || Array.isArray(payload.services)
    ) {
      return;
    }

    const allowed = new Set(SERVICES.map(([key]) => key));
    const now = Date.now();
    for (const [key, value] of Object.entries(payload.services)) {
      if (!allowed.has(key) || !value || typeof value !== "object" || Array.isArray(value)) continue;
      const lastAttempt = persistedObservationStamp(value.last_attempt_ms, now);
      const lastConfirmed = persistedObservationStamp(value.last_confirmed_ms, now);
      const lastGreen = persistedObservationStamp(value.last_green_ms, now);
      if (lastAttempt === null && lastConfirmed === null && lastGreen === null) continue;
      serviceObservations.set(key, {
        last_attempt_ms: lastAttempt,
        last_confirmed_ms: lastConfirmed,
        last_green_ms: lastGreen,
      });
    }
  }

  function persistServiceObservations() {
    const allowed = new Set(SERVICES.map(([key]) => key));
    const now = Date.now();
    const services = {};
    for (const [key, value] of serviceObservations.entries()) {
      if (!allowed.has(key) || !value || typeof value !== "object") continue;
      const lastAttempt = persistedObservationStamp(value.last_attempt_ms, now);
      const lastConfirmed = persistedObservationStamp(value.last_confirmed_ms, now);
      const lastGreen = persistedObservationStamp(value.last_green_ms, now);
      if (lastAttempt === null && lastConfirmed === null && lastGreen === null) continue;
      services[key] = {
        last_attempt_ms: lastAttempt,
        last_confirmed_ms: lastConfirmed,
        last_green_ms: lastGreen,
      };
    }
    const payload = {
      format: "bodyrig-drift-service-observations",
      version: 1,
      saved_ms: now,
      services,
    };
    try {
      window.localStorage.setItem(
        SERVICE_OBSERVATION_STORAGE_KEY,
        JSON.stringify(payload)
      );
    } catch {
      // Monitoring persistence is contextual only; storage failure never changes authority.
    }
  }

  function panel() {
    return document.getElementById("tab-operations");
  }

  function currentPersonId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function photorealStateLabel(state) {
    return ({
      complete: "Komplet",
      required: "Næste trin",
      "human-review-required": "Human review",
      "operator-input-required": "Input kræves",
      blocked: "Blokeret",
      "no-run": "Ingen run",
    })[state] || state || "Ukendt";
  }

  function photorealAttention(value) {
    if (!value || typeof value !== "object") return "Photoreal / ExAvatar";
    const state = String(value.state || "unknown");
    if (state === "no-run" || state === "complete") return null;
    if (value.exavatar?.busy === true) return null;
    const gate = String(value.pipeline?.next_gate || "").trim();
    if (state === "required") return `Photoreal (næste gate${gate ? `: ${gate}` : ""})`;
    if (state === "human-review-required") return `Photoreal (human review${gate ? `: ${gate}` : ""})`;
    if (state === "operator-input-required") return `Photoreal (input kræves${gate ? `: ${gate}` : ""})`;
    if (state === "blocked") return `Photoreal (blokeret${gate ? `: ${gate}` : ""})`;
    return `Photoreal (${photorealStateLabel(state)})`;
  }

  function renderPhotorealHistory(value) {
    const host = document.getElementById("operator-photoreal-history");
    if (!host) return;
    host.replaceChildren();
    const history = Array.isArray(value?.history) ? value.history : [];
    if (!history.length) {
      const empty = document.createElement("div");
      empty.className = "muted-text";
      empty.textContent = "Ingen performer-bundne Photoreal-runs fundet.";
      host.appendChild(empty);
      return;
    }

    for (const run of history) {
      if (!run || typeof run !== "object") continue;
      const row = document.createElement("div");
      row.className = "operator-photoreal-history-row";

      const copy = document.createElement("div");
      copy.className = "operator-photoreal-history-copy";
      const title = document.createElement("strong");
      title.textContent = String(run.name || "ukendt run");

      const meta = document.createElement("div");
      meta.className = "fine-print";
      const teacherSha = String(run.teacher_input_sha256 || "");
      const live = run.live_evidence && typeof run.live_evidence === "object"
        ? run.live_evidence
        : null;
      meta.textContent = [
        run.current === true ? "CURRENT" : "HISTORY-ONLY",
        run.modified_utc || "ukendt tid",
        `P0 status ${run.p0_status_present === true ? "ja" : "nej"}`,
        `calibration ${run.calibration_state || "ukendt"}`,
        `teacher input ${run.teacher_input_valid === true ? "valid" : (run.teacher_input_present === true ? "invalid" : "mangler")}`,
        `teacher config ${run.teacher_config_present === true ? "ja" : "nej"}`,
        `teacher manifest ${run.teacher_manifest_present === true ? "ja" : "nej"}`,
        teacherSha ? `teacher SHA ${teacherSha.slice(0, 12)}…` : "",
        live ? `ExAvatar ${live.phase || "ukendt"}` : "",
        live && Number.isInteger(live.highest_snapshot_epoch)
          ? `checkpoint ${live.highest_snapshot_epoch}`
          : "",
        live && live.latest_log_name
          ? `log ${live.latest_log_name} · ${live.latest_log_modified_utc || "ukendt tid"}`
          : "",
      ].filter(Boolean).join(" · ");

      const path = document.createElement("div");
      path.className = "operator-photoreal-history-path";
      path.textContent = [
        String(run.path || ""),
        run.workspace ? `workspace ${run.workspace}` : "",
      ].filter(Boolean).join(" · ");

      copy.append(title, meta, path);

      const badge = document.createElement("span");
      const continuation = run.continuation_candidate === true;
      badge.className = `badge${continuation ? "" : " muted"}`;
      badge.textContent = continuation ? "CONTINUATION" : "EVIDENCE";

      row.append(copy, badge);
      host.appendChild(row);
    }
  }

  function renderPhotoreal(result) {
    const summary = document.getElementById("operator-photoreal-summary");
    const detail = document.getElementById("operator-photoreal-detail");
    if (!summary || !detail) return;
    if (result?.ok === false) {
      summary.textContent = result.error || "Photoreal-status kunne ikke læses.";
      detail.textContent = "Fail-closed: Drift kan ikke bekræfte den valgte persons Photoreal/ExAvatar-status.";
      renderPhotorealHistory({ history: [] });
      setBadge("operator-photoreal-badge", false, "Offline");
      return;
    }
    const value = result?.value || {};
    const state = String(value.state || "unknown");
    const pipeline = value.pipeline && typeof value.pipeline === "object" ? value.pipeline : {};
    const exavatar = value.exavatar && typeof value.exavatar === "object" ? value.exavatar : {};
    const busy = exavatar.busy === true;
    const neutral = state === "no-run";
    const healthy = state === "complete" || busy;
    const gate = String(pipeline.next_gate || "").trim();
    const phase = String(exavatar.phase || "ukendt");
    const performer = value.performer?.name || value.performer?.id || "valgt person";
    summary.textContent = neutral
      ? `${performer} · ingen Photoreal-run`
      : `${performer} · ${photorealStateLabel(state)}${gate ? ` · ${gate}` : ""} · ExAvatar ${busy ? "kører" : phase}`;
    setBadge(
      "operator-photoreal-badge",
      healthy,
      busy ? "Kører" : (neutral ? "Inaktiv" : photorealStateLabel(state))
    );
    const active = Array.isArray(exavatar.active_processes) ? exavatar.active_processes : [];
    const latest = exavatar.latest_log && typeof exavatar.latest_log === "object" ? exavatar.latest_log : {};
    detail.textContent = [
      `State: ${state}`,
      `Next gate: ${gate || "—"}`,
      `Message: ${pipeline.message || value.monitoring_note || "—"}`,
      `ExAvatar phase: ${phase}`,
      `Busy: ${busy ? "ja" : "nej"}`,
      `Workspace: ${exavatar.linux_workspace || value.teacher_work_root || "—"}`,
      `Preprocess: ${Number(exavatar.preprocess_completed_count || 0)}/${Number(exavatar.preprocess_total_count || 9)}`,
      `Highest checkpoint: ${exavatar.highest_snapshot_epoch ?? "—"} / target ${exavatar.training_target_epoch ?? 4}`,
      `Neutral renders: ${Number(exavatar.neutral_render_count || 0)}/50`,
      `Aktive processer: ${active.length}`,
      `Seneste log: ${latest.name || "—"} · ${latest.modified_utc || "ukendt tid"}`,
      `Advance allowed: ${value.advance_allowed === true ? "ja" : "nej"}`,
      `Production activation: ${value.authority?.production_activation === true ? "ja" : "nej"}`,
    ].join("\n");
    renderPhotorealHistory(value);
  }

  const DIGITAL_TWIN_MILESTONE_LABELS = {
    m1: "M1",
    m2: "M2",
    m3: "M3",
    m4: "M4",
    m5: "M5",
    m6: "M6",
  };

  function digitalTwinAttention(result) {
    if (!currentPersonId()) return null;
    if (result?.ok === false) return "Digital twin M1–M6";
    const value = result?.value;
    if (!value || typeof value !== "object") return "Digital twin M1–M6";
    if (value.digital_twin_ready === true && value.production_activation === true) return null;
    const gate = String(value.next_gate || "").trim();
    return `Digital twin${gate ? ` (${gate})` : ""}`;
  }

  const DIGITAL_TWIN_COMPONENT_LABELS = {
    source_capture: "Source capture",
    review: "Render + human review",
    finalized: "Finalized authority",
  };

  function componentStateLabel(state) {
    return ({
      complete: "PASS",
      required: "Kræves",
      blocked: "Blokeret",
    })[state] || state || "Ukendt";
  }

  function renderDigitalTwinComponents(value) {
    const host = document.getElementById("operator-digital-twin-components");
    if (!host) return;
    host.replaceChildren();

    const progress = value?.component_progress && typeof value.component_progress === "object"
      ? value.component_progress
      : {};
    for (const [milestone, title] of [["m2", "M2 · Hands / feet / nails"], ["m3", "M3 · Wardrobe / footwear"]]) {
      const component = progress[milestone] && typeof progress[milestone] === "object"
        ? progress[milestone]
        : null;
      const section = document.createElement("section");
      section.className = "operator-twin-component";
      const heading = document.createElement("strong");
      heading.textContent = title;
      section.appendChild(heading);

      if (!component) {
        const missing = document.createElement("div");
        missing.className = "fine-print";
        missing.textContent = "Substage evidence mangler fra read-only status.";
        section.appendChild(missing);
        host.appendChild(section);
        continue;
      }

      const grid = document.createElement("div");
      grid.className = "operator-twin-component-stages";
      for (const key of ["source_capture", "review", "finalized"]) {
        const stage = component[key] && typeof component[key] === "object"
          ? component[key]
          : { state: "blocked", message: "Status mangler." };
        const node = document.createElement("div");
        node.className = `operator-twin-component-stage ${stage.complete === true ? "complete" : "pending"}`;

        const label = document.createElement("strong");
        label.textContent = DIGITAL_TWIN_COMPONENT_LABELS[key];
        const state = document.createElement("span");
        state.textContent = componentStateLabel(String(stage.state || ""));
        const detail = document.createElement("span");
        detail.className = "operator-twin-component-detail";
        const counts = [];
        if (Number.isInteger(stage.valid_count)) counts.push(`${stage.valid_count} valid`);
        if (Number.isInteger(stage.rejected_count) && stage.rejected_count > 0) counts.push(`${stage.rejected_count} afvist`);
        const authorityId = String(stage.authority_id || "");
        const ids = Array.isArray(stage.candidate_ids)
          ? stage.candidate_ids.map((item) => String(item || "")).filter(Boolean).slice(0, 8)
          : [];
        detail.textContent = [
          counts.join(" · "),
          authorityId ? `authority ${authorityId}` : "",
          ids.length ? `evidence ${ids.join(", ")}` : "",
          stage.scan_truncated === true ? "bounded scan" : "",
          String(stage.message || ""),
        ].filter(Boolean).join(" · ");

        node.append(label, state, detail);
        grid.appendChild(node);
      }
      section.appendChild(grid);

      const next = document.createElement("div");
      next.className = "fine-print";
      next.textContent = component.next_substage === "complete"
        ? "Substage-kæden er komplet."
        : `Næste observerede substage: ${DIGITAL_TWIN_COMPONENT_LABELS[component.next_substage] || component.next_substage || "ukendt"}.`;
      section.appendChild(next);
      host.appendChild(section);
    }
  }

  const DIGITAL_TWIN_REALIZATION_STAGES = {
    m4: [
      ["composition", "Composition authority"],
      ["physical_acceptance", "Physical acceptance"],
    ],
    m5: [
      ["windows", "Windows realization"],
      ["quest", "Quest realization"],
      ["finalized", "M5 finalized"],
    ],
    m6: [
      ["release", "Canonical M6 release"],
    ],
  };

  function renderDigitalTwinRealization(value) {
    const host = document.getElementById("operator-digital-twin-realization");
    if (!host) return;
    host.replaceChildren();

    const progress = value?.realization_progress && typeof value.realization_progress === "object"
      ? value.realization_progress
      : {};
    for (const [milestone, title] of [["m4", "M4 · Composition / acceptance"], ["m5", "M5 · Windows / Quest"], ["m6", "M6 · Canonical release"]]) {
      const item = progress[milestone] && typeof progress[milestone] === "object"
        ? progress[milestone]
        : null;
      const section = document.createElement("section");
      section.className = "operator-twin-component";
      const heading = document.createElement("strong");
      heading.textContent = title;
      section.appendChild(heading);

      if (!item) {
        const missing = document.createElement("div");
        missing.className = "fine-print";
        missing.textContent = "Realization evidence mangler fra read-only status.";
        section.appendChild(missing);
        host.appendChild(section);
        continue;
      }

      const grid = document.createElement("div");
      grid.className = "operator-twin-component-stages";
      const definitions = DIGITAL_TWIN_REALIZATION_STAGES[milestone] || [];
      for (const [key, labelText] of definitions) {
        const stage = item[key] && typeof item[key] === "object"
          ? item[key]
          : { state: "blocked", message: "Status mangler." };
        const node = document.createElement("div");
        node.className = `operator-twin-component-stage ${stage.complete === true ? "complete" : "pending"}`;

        const label = document.createElement("strong");
        label.textContent = labelText;
        const state = document.createElement("span");
        state.textContent = componentStateLabel(String(stage.state || ""));
        const detail = document.createElement("span");
        detail.className = "operator-twin-component-detail";
        detail.textContent = [
          stage.authority_id ? `authority ${stage.authority_id}` : "",
          stage.evidence_dir ? `evidence ${stage.evidence_dir}` : "",
          String(stage.message || ""),
        ].filter(Boolean).join(" · ");

        node.append(label, state, detail);
        grid.appendChild(node);
      }
      section.appendChild(grid);

      const next = document.createElement("div");
      next.className = "fine-print";
      next.textContent = item.next_substage === "complete"
        ? "Realization-kæden er komplet."
        : `Næste observerede substage: ${(DIGITAL_TWIN_REALIZATION_STAGES[milestone] || []).find(([key]) => key === item.next_substage)?.[1] || item.next_substage || "ukendt"}.`;
      section.appendChild(next);
      host.appendChild(section);
    }
  }

  function renderDigitalTwin(result) {
    const summary = document.getElementById("operator-digital-twin-summary");
    const stages = document.getElementById("operator-digital-twin-stages");
    const detail = document.getElementById("operator-digital-twin-detail");
    if (!summary || !stages || !detail) return;
    stages.replaceChildren();

    if (result?.ok === false) {
      summary.textContent = result.error || "Digital-twin status kunne ikke læses.";
      detail.textContent = "Fail-closed: Drift kan ikke strict-validere M1–M6 for den valgte person.";
      renderDigitalTwinComponents({});
      renderDigitalTwinRealization({});
      setBadge("operator-digital-twin-badge", false, "Offline");
      return;
    }

    const value = result?.value || {};
    const milestoneValues = value.milestones && typeof value.milestones === "object"
      ? value.milestones
      : {};
    for (const key of Object.keys(DIGITAL_TWIN_MILESTONE_LABELS)) {
      const item = milestoneValues[key] && typeof milestoneValues[key] === "object"
        ? milestoneValues[key]
        : { state: "blocked", message: "Status mangler." };
      const node = document.createElement("div");
      node.className = `operator-twin-stage ${item.state === "complete" ? "complete" : "pending"}`;
      node.title = String(item.message || "");
      const label = document.createElement("strong");
      label.textContent = DIGITAL_TWIN_MILESTONE_LABELS[key];
      const state = document.createElement("span");
      state.textContent = item.state === "complete"
        ? "PASS"
        : item.state === "required"
          ? "Kræves"
          : item.state === "blocked"
            ? "Blokeret"
            : String(item.state || "Ukendt");
      node.append(label, state);
      stages.appendChild(node);
    }

    const ready = value.digital_twin_ready === true && value.production_activation === true;
    const unassembled = value.state === "not-assembled";
    setBadge(
      "operator-digital-twin-badge",
      ready,
      ready ? "M6 klar" : (unassembled ? "Ikke samlet" : (value.state === "required" ? "Næste gate" : "Blokeret"))
    );
    summary.textContent = [
      value.person_revision || "ingen aktiv Person Revision",
      value.body_revision || "",
      ready ? "digital twin aktiv" : `next: ${value.next_gate || "ukendt"}`,
    ].filter(Boolean).join(" · ");
    detail.textContent = [
      String(value.message || "—"),
      `Digital twin ready: ${value.digital_twin_ready === true ? "ja" : "nej"}`,
      `Production activation: ${value.production_activation === true ? "ja" : "nej"}`,
      value.physical_acceptance_dir ? `Acceptance: ${value.physical_acceptance_dir}` : "",
    ].filter(Boolean).join("\n");
    renderDigitalTwinComponents(value);
    renderDigitalTwinRealization(value);
  }

  function visible() {
    const button = document.querySelector('.tab[data-tab="operations"]');
    return Boolean(button?.classList.contains("active"));
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
      cache: "no-store",
    });
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`);
    return payload;
  }

  async function readApi(url, timeoutMs = SERVICE_READ_TIMEOUT_MS) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const started = Date.now();
    try {
      const value = await api(url, { signal: controller.signal });
      const observed = Date.now();
      return {
        value,
        observed_ms: observed,
        latency_ms: Math.max(0, observed - started),
      };
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error(`monitor read timeout efter ${Math.round(timeoutMs / 1000)} s`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function serviceBlockers(key, value) {
    const blockers = [];
    if (!value || typeof value !== "object") return ["health payload mangler"];

    if (key === "bodyrig") {
      if (value.ok !== true) blockers.push("BodyRig health ok mangler");
      if (value.physical_build_ready !== true) {
        blockers.push(value.physical_build_reason || "physical build authority er ikke klar");
      }
      return blockers;
    }
    if (key === "operator") {
      if (value.ok !== true) blockers.push(value.reason || "operator checkout er ikke authoritative");
      return blockers;
    }
    if (key === "stash") {
      if (value.ok !== true) blockers.push("Stash health ok mangler");
      if (value.performer_read !== true) blockers.push("performer-read capability mangler");
      return blockers;
    }
    if (key === "modelrig") {
      if (value.ok !== true) blockers.push("ModelRig health ok mangler");
      if (value.service !== "modelrig-server") blockers.push("forventet ModelRig service-id mangler");
      return blockers;
    }
    if (key === "voicerig") {
      if (value.ok !== true) blockers.push("VoiceRig health ok mangler");
      if (value.service !== "voicerig") blockers.push("forventet VoiceRig service-id mangler");
      return blockers;
    }
    if (key === "runtime") {
      if (
        !Object.prototype.hasOwnProperty.call(value, "updated_at")
        || typeof value.updated_at !== "number"
        || !Number.isFinite(value.updated_at)
        || value.updated_at <= 0
      ) {
        blockers.push("runtime state mangler gyldigt updated_at");
      }
      return blockers;
    }
    if (key === "system") {
      if (Array.isArray(value.blockers)) {
        for (const item of value.blockers) {
          const text = typeof item === "string" ? item.trim() : "";
          if (text && text.length <= 1000) blockers.push(text);
        }
        if (value.ready !== true && blockers.length === 0) {
          blockers.push("system-readiness er blokeret uden gyldig blocker-evidence");
        }
        return blockers;
      }
      if (value.wsl_cuda?.ready !== true) blockers.push("WSL/CUDA readiness er blokeret");
      if (value.powershell_7 !== true) blockers.push("PowerShell 7 mangler");
      return blockers;
    }
    if (value.ok !== true) blockers.push("health ok mangler");
    return blockers;
  }

  function recordServiceObservation(key, result) {
    const previous = serviceObservations.get(key) || {};
    const observedMs = Number.isFinite(result?.observed_ms) ? result.observed_ms : null;
    const blockers = result?.ok === true ? serviceBlockers(key, result.value) : [];
    const healthy = result?.ok === true && blockers.length === 0;
    const observation = {
      last_attempt_ms: Date.now(),
      last_confirmed_ms: result?.ok === true && observedMs !== null
        ? observedMs
        : (previous.last_confirmed_ms ?? null),
      last_green_ms: healthy && observedMs !== null
        ? observedMs
        : (previous.last_green_ms ?? null),
    };
    serviceObservations.set(key, observation);
    persistServiceObservations();
    return {
      ...result,
      blockers,
      last_confirmed_ms: observation.last_confirmed_ms,
      last_green_ms: observation.last_green_ms,
    };
  }

  function serviceResultFresh(result, now = Date.now()) {
    if (result?.ok !== true || !Number.isFinite(result?.observed_ms)) return false;
    const age = Math.max(0, now - result.observed_ms);
    return age <= SERVICE_STALE_MS;
  }

  function ageLabel(stampMs, now = Date.now()) {
    if (!Number.isFinite(stampMs)) return "aldrig";
    const seconds = Math.max(0, Math.round((now - stampMs) / 1000));
    if (seconds < 60) return `${seconds} s siden`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} min siden`;
    return `${Math.round(minutes / 60)} t siden`;
  }

  function serviceObservationLabel(result) {
    const lastGreen = Number.isFinite(result?.last_green_ms)
      ? ` · sidst grøn ${ageLabel(result.last_green_ms)}`
      : "";
    if (result?.ok === true && Number.isFinite(result?.observed_ms)) {
      const latency = Number.isFinite(result.latency_ms) ? ` · ${result.latency_ms} ms` : "";
      const blocked = Array.isArray(result?.blockers) && result.blockers.length > 0;
      return `bekræftet ${ageLabel(result.observed_ms)}${latency}${blocked ? lastGreen : ""}`;
    }
    if (Number.isFinite(result?.last_confirmed_ms)) {
      return `sidst bekræftet ${ageLabel(result.last_confirmed_ms)}${lastGreen}`;
    }
    if (lastGreen) return `intet bekræftet svar${lastGreen}`;
    return "intet bekræftet svar";
  }

  function setBadge(id, ok, text) {
    const badge = document.getElementById(id);
    if (!badge) return;
    badge.textContent = text;
    badge.classList.toggle("muted", !ok);
  }

  function markServicesChecking() {
    for (const [key] of SERVICES) {
      setBadge(`operator-${key}-badge`, false, "Kontrollerer");
    }
    document.getElementById("operator-system-actions")?.replaceChildren();
  }

  function serviceSummary(key, value) {
    if (key === "bodyrig") {
      return `v${value.version || "?"} · ${value.people ?? "?"} personer · physical build ${value.physical_build_ready === true ? "klar" : "blokeret"}`;
    }
    if (key === "operator") {
      return value.ok === true
        ? `clean authority · ${String(value.bodyrig_revision || value.revision || "").slice(0, 12)}`
        : (value.reason || "Operator checkout er ikke authoritative.");
    }
    if (key === "stash") {
      return `Stash ${value.version || "?"} · performer-read ${value.performer_read === true ? "klar" : "mangler"}`;
    }
    if (key === "modelrig") {
      return `${value.service || "modelrig"} · v${value.version || "?"}`;
    }
    if (key === "voicerig") {
      return `${value.service || "voicerig"} · v${value.version || "?"}`;
    }
    if (key === "runtime") {
      return `aktiv body ${value.active_body_id || "ingen"} · revision ${value.revision ?? value.generation ?? "?"}`;
    }
    if (key === "system") {
      const wsl = value.wsl_cuda || {};
      const quest = value.quest || {};
      const gpu = wsl.gpu?.summary || "ingen GPU";
      const cuda = wsl.cuda?.version || "?";
      const active = Array.isArray(wsl.active_exavatar_processes) ? wsl.active_exavatar_processes.length : 0;
      return `WSL/CUDA ${wsl.ready === true ? "klar" : "blokeret"} · CUDA ${cuda} · ${gpu} · ExAvatar ${active ? `aktiv (${active})` : "idle"} · Quest ${quest.quest_device_count ?? 0}`;
    }
    return JSON.stringify(value);
  }

  function renderSystemDetail(value) {
    const target = document.getElementById("operator-system-detail");
    if (!target) return;
    const wsl = value?.wsl_cuda || {};
    const quest = value?.quest || {};
    const cuda = wsl.cuda || {};
    const gpu = wsl.gpu || {};
    const active = Array.isArray(wsl.active_exavatar_processes) ? wsl.active_exavatar_processes : [];
    const devices = Array.isArray(quest.devices) ? quest.devices : [];
    const lines = [
      `WSL distro: ${wsl.distribution || "?"}`,
      `GPU: ${gpu.summary || "ikke fundet"}`,
      `CUDA: ${cuda.version || "?"} / krævet ${cuda.required_version || "?"}`,
      `ExAvatar runtime: ${wsl.exavatar_runtime_complete === true ? "komplet" : "mangler/ufuldstændig"}`,
      `Runtime receipt: ${wsl.exavatar_runtime_receipt === true ? "ja" : "nej"}`,
      `Photoreal materializer: ${wsl.materializer_runtime === true ? "klar" : "mangler"}`,
      `Pinned public deps: ${wsl.public_dependencies === true ? "klar" : "mangler"}`,
      `Aktive ExAvatar-processer: ${active.length}`,
      `Unity: ${quest.unity_version || "?"} · pinned adb: ${quest.adb_present === true ? "klar" : "mangler"}`,
      `Quest/Oculus online: ${quest.quest_device_count ?? 0}`,
    ];
    if (active.length) {
      lines.push("", "Aktive processer:");
      for (const item of active.slice(0, 8)) lines.push(`  ${item}`);
    }
    if (devices.length) {
      lines.push("", "ADB-enheder:");
      for (const item of devices.slice(0, 8)) {
        lines.push(`  ${item.serial || "?"} · ${item.model || "ukendt"}${item.quest_class === true ? " · Quest" : ""}`);
      }
    }
    target.textContent = lines.join("\n");
  }

  function serviceHealthy(key, value) {
    return serviceBlockers(key, value).length === 0;
  }

  function renderServiceWhy(key, reasons) {
    const target = document.getElementById(`operator-${key}-why`);
    if (!target) return;
    const clean = Array.isArray(reasons)
      ? reasons
          .map((item) => String(item || "").trim())
          .filter(Boolean)
          .slice(0, 12)
      : [];
    if (!clean.length) {
      target.textContent = "";
      target.classList.add("hidden");
      return;
    }
    target.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = "Hvorfor?";
    const list = document.createElement("ul");
    for (const reason of clean) {
      const item = document.createElement("li");
      item.textContent = reason;
      list.appendChild(item);
    }
    target.append(title, list);
    target.classList.remove("hidden");
  }

  function renderService(key, label, result) {
    const summary = document.getElementById(`operator-${key}-summary`);
    const badgeId = `operator-${key}-badge`;
    if (!summary) return;
    const observation = serviceObservationLabel(result);
    if (result.ok === false && result.error) {
      summary.textContent = `${result.error} · ${observation}`;
      setBadge(badgeId, false, "Offline");
      renderServiceWhy(key, [
        `Monitoring read fejlede: ${result.error}`,
        Number.isFinite(result?.last_confirmed_ms)
          ? `Seneste bekræftede svar: ${ageLabel(result.last_confirmed_ms)}`
          : "Der findes intet tidligere bekræftet svar i den lokale observation-history.",
      ]);
      if (key === "system") {
        const detail = document.getElementById("operator-system-detail");
        if (detail) detail.textContent = "Fail-closed: system-readiness kunne ikke bekræftes.";
        document.getElementById("operator-system-actions")?.replaceChildren();
      }
      return;
    }
    const value = result.value || {};
    const blockers = Array.isArray(result.blockers) ? result.blockers : serviceBlockers(key, value);
    const fresh = serviceResultFresh(result);
    const healthy = blockers.length === 0 && fresh;
    const freshnessText = fresh ? "" : " · STALE health-evidence";
    summary.textContent = `${serviceSummary(key, value)} · ${observation}${freshnessText}`;
    setBadge(badgeId, healthy, healthy ? "Klar" : (fresh ? "Blokeret" : "Stale"));
    const why = blockers.slice();
    if (!fresh) {
      why.unshift(`Health-evidence er ældre end ${Math.round(SERVICE_STALE_MS / 1000)} s og kan ikke bruges som grøn authority.`);
    }
    renderServiceWhy(key, why);
    if (key === "system") {
      renderSystemDetail(value);
      if (fresh) renderSystemActions(value);
      else document.getElementById("operator-system-actions")?.replaceChildren();
    }
  }

  async function runSystemAction(action, button, mutatesEnvironment = false) {
    if (!action || !button) return;
    if (mutatesEnvironment) {
      const accepted = window.confirm(
        "Denne canonicale handling ændrer WSL/ExAvatar-miljøet. Den bruger aldrig -Force og er kun tilgængelig, når ingen ExAvatar-proces kører. Fortsæt?"
      );
      if (!accepted) return;
    }
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Starter…";
    const summary = document.getElementById("operatorSummary");
    try {
      const result = await api("/api/v1/operator/system-readiness/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      if (summary) summary.textContent = `System-preflight startet · PID ${result.launch?.pid || "?"}. Resultatet skrives til operator-loggen.`;
      setTimeout(() => void refresh(true), 1800);
    } catch (error) {
      if (summary) summary.textContent = `Systemhandling afvist: ${error.message}`;
      button.disabled = false;
      button.textContent = original;
    }
  }

  function renderSystemActions(value) {
    const host = document.getElementById("operator-system-actions");
    if (!host) return;
    host.replaceChildren();
    const actions = Array.isArray(value?.actions) ? value.actions : [];
    for (const action of actions) {
      const id = String(action?.id || "");
      if (!id) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = action.label || id;
      button.title = action.mutates_environment === true
        ? "Denne handling kan ændre miljøet."
        : "Read-only canonical preflight.";
      button.addEventListener("click", () => void runSystemAction(id, button, action.mutates_environment === true));
      host.appendChild(button);
    }
  }

  function jobLabel(job) {
    const kind = String(job.kind || "job");
    const person = String(job.person_id || "");
    const stage = String(job.stage || job.resume_stage || "");
    return [kind, person, stage].filter(Boolean).join(" · ");
  }

  function jobStatusLabel(status) {
    return ({
      uploading: "Uploader",
      queued: "I kø",
      running: "Kører",
      needs_speaker: "Vælg speaker",
      needs_reference: "Vælg reference",
      cancelling: "Annullerer",
      succeeded: "Færdig",
      failed: "Fejlet",
      canceled: "Annulleret",
      interrupted: "Afbrudt",
    })[status] || status || "Ukendt";
  }

  function jobCanCancel(job) {
    const status = String(job?.status || "");
    if (String(job?.kind || "") === "voice-build") {
      return OPEN_JOB_STATES.has(status) && status !== "cancelling";
    }
    return String(job?.kind || "") === "body-build" && status === "queued";
  }

  async function hydrateOpenVoiceJobs(payload) {
    if (payload?.error) return payload;
    const jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
    const hydrated = await Promise.all(
      jobs.map(async (job) => {
        const status = String(job?.status || "");
        const jobId = String(job?.job_id || "");
        if (
          String(job?.kind || "") !== "voice-build"
          || !OPEN_JOB_STATES.has(status)
          || !jobId
        ) {
          return job;
        }
        try {
          return (await readApi(`/api/v1/jobs/${encodeURIComponent(jobId)}`)).value;
        } catch (error) {
          return {
            ...job,
            speaker_choices: null,
            reference_choices: null,
            monitoring_error: `Authoritative VoiceRig-status kunne ikke hentes: ${error.message}`,
          };
        }
      })
    );
    return { ...payload, jobs: hydrated };
  }

  function voiceChoiceValid(kind, choice) {
    if (!choice || typeof choice !== "object") return false;
    if (kind === "speaker") {
      const anchor = String(choice.anchor || "").trim();
      return anchor.length >= 3 && anchor.length <= 64;
    }
    if (kind === "reference") {
      const selected = Number(choice.choice);
      return Number.isInteger(selected) && selected >= 1 && selected <= 4;
    }
    return false;
  }

  async function chooseVoiceJobInput(job, kind, choice, button) {
    const jobId = String(job?.job_id || "");
    const status = String(job?.status || "");
    if (!jobId || String(job?.kind || "") !== "voice-build") return;
    if (kind === "speaker" && status !== "needs_speaker") return;
    if (kind === "reference" && status !== "needs_reference") return;

    let suffix = "";
    if (kind === "speaker") {
      const anchor = String(choice?.anchor || "").trim();
      if (anchor.length < 3 || anchor.length > 64) return;
      suffix = `/speaker?anchor=${encodeURIComponent(anchor)}`;
    } else {
      const selected = Number(choice?.choice);
      if (!Number.isInteger(selected) || selected < 1 || selected > 4) return;
      suffix = `/reference?choice=${encodeURIComponent(selected)}`;
    }

    const original = button?.textContent || "Vælg";
    if (button) {
      button.disabled = true;
      button.textContent = "Vælger…";
    }
    try {
      await api(`/api/v1/jobs/${encodeURIComponent(jobId)}${suffix}`, { method: "POST" });
      await refresh(true);
    } catch (error) {
      const statusNode = document.getElementById("operatorJobsStatus");
      if (statusNode) statusNode.textContent = `VoiceRig-valg blev afvist: ${error.message}`;
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
  }

  function renderVoiceJobChoices(meta, job) {
    const status = String(job?.status || "");
    if (String(job?.kind || "") !== "voice-build" || !ACTION_JOB_STATES.has(status)) return;
    if (job?.monitoring_error) return;

    const choices = status === "needs_speaker"
      ? job.speaker_choices
      : job.reference_choices;
    const kind = status === "needs_speaker" ? "speaker" : "reference";

    if (!Array.isArray(choices) || !choices.length) {
      const missing = document.createElement("div");
      missing.className = "operator-job-error";
      missing.textContent = "VoiceRig kræver operator-input, men authoritative choice-evidence mangler. Drift vælger aldrig en fallback automatisk.";
      meta.appendChild(missing);
      return;
    }

    const list = document.createElement("div");
    list.className = "operator-voice-choice-list";
    for (const choice of choices) {
      if (!voiceChoiceValid(kind, choice)) continue;
      const card = document.createElement("div");
      card.className = "operator-voice-choice";

      const copy = document.createElement("div");
      copy.className = "operator-voice-choice-copy";
      const title = document.createElement("strong");
      title.textContent = String(
        choice.label
        || (kind === "speaker" ? choice.anchor : `Reference ${choice.choice ?? "?"}`)
      );
      const detail = document.createElement("div");
      detail.className = "fine-print";
      detail.textContent = kind === "speaker"
        ? `${Number(choice.speech_seconds || 0).toFixed(1)} s tale · ${String(choice.anchor || "")}`
        : `Quality ${choice.quality_score ?? "?"} · ${Number(choice.reference_seconds || 0).toFixed(1)} s reference`;
      copy.append(title, detail);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = "Vælg";
      button.addEventListener("click", () => void chooseVoiceJobInput(job, kind, choice, button));

      card.append(copy, button);

      if (typeof choice.preview_wav_base64 === "string" && choice.preview_wav_base64) {
        const audio = document.createElement("audio");
        audio.controls = true;
        audio.preload = "none";
        audio.className = "operator-voice-choice-audio";
        audio.src = `data:audio/wav;base64,${choice.preview_wav_base64}`;
        card.appendChild(audio);
      }
      list.appendChild(card);
    }

    if (!list.childElementCount) {
      const missing = document.createElement("div");
      missing.className = "operator-job-error";
      missing.textContent = "VoiceRig choice-listen indeholder ingen gyldige valg; ingen handling udføres.";
      meta.appendChild(missing);
      return;
    }
    meta.appendChild(list);
  }

  function jobStateMatches(job, filter) {
    const status = String(job?.status || "");
    if (filter === "open") return OPEN_JOB_STATES.has(status);
    if (filter === "action") return ACTION_JOB_STATES.has(status);
    if (filter === "failure") return ["failed", "interrupted"].includes(status);
    if (filter === "final") return !OPEN_JOB_STATES.has(status);
    return true;
  }

  function filteredJobs(jobs) {
    const personFilter = document.getElementById("operatorJobPersonFilter")?.value || "all";
    const kindFilter = document.getElementById("operatorJobKindFilter")?.value || "all";
    const stateFilter = document.getElementById("operatorJobStateFilter")?.value || "all";
    const search = (document.getElementById("operatorJobSearch")?.value || "").trim().toLowerCase();
    const selectedPerson = currentPersonId();

    return jobs.filter((job) => {
      if (personFilter === "current" && String(job?.person_id || "") !== selectedPerson) return false;
      if (kindFilter !== "all" && String(job?.kind || "") !== kindFilter) return false;
      if (!jobStateMatches(job, stateFilter)) return false;
      if (!search) return true;
      const haystack = [
        job?.job_id,
        job?.person_id,
        job?.kind,
        job?.status,
        job?.stage,
        job?.resume_stage,
        job?.bodyrig_revision,
        job?.body_revision,
        job?.canonical_body_id,
        job?.voice_revision,
        job?.voice_package,
        job?.voicerig_job_id,
        job?.message,
        job?.error,
      ].map((value) => String(value || "").toLowerCase()).join("\n");
      return haystack.includes(search);
    });
  }

  function jobEvidenceLines(job) {
    const fields = [
      ["Job id", job?.job_id],
      ["Kind", job?.kind],
      ["Person", job?.person_id],
      ["Status", job?.status],
      ["Stage", job?.stage || job?.resume_stage],
      ["BodyRig revision", job?.bodyrig_revision],
      ["Body revision", job?.body_revision],
      ["Canonical body id", job?.canonical_body_id],
      ["Voice revision", job?.voice_revision],
      ["VoiceRig job id", job?.voicerig_job_id],
      ["Voice package", job?.voice_package],
      ["Progress kind", job?.progress_kind],
      ["Progress", typeof job?.progress === "number" ? job.progress : null],
      ["Elapsed seconds", typeof job?.elapsed_seconds === "number" ? job.elapsed_seconds : null],
      ["Source manifest SHA-256", job?.source_manifest_sha256],
      ["Source binding SHA-256", job?.source_binding_sha256],
      ["Body review SHA-256", job?.body_review_sha256],
      ["Package SHA-256", job?.package_sha256],
      ["Adjustment feedback SHA-256", job?.adjustment_feedback_sha256],
      ["Created", job?.created_utc],
      ["Started", job?.started_utc],
      ["Completed", job?.completed_utc],
      ["PID", job?.pid],
    ];
    return fields
      .filter(([, value]) => value !== undefined && value !== null && String(value) !== "")
      .map(([label, value]) => `${label}: ${value}`);
  }

  function appendJobEvidence(meta, job) {
    const lines = jobEvidenceLines(job);
    if (!lines.length) return;
    const details = document.createElement("details");
    details.className = "operator-job-evidence";
    const summary = document.createElement("summary");
    summary.textContent = "Evidence / detaljer";
    const pre = document.createElement("pre");
    pre.className = "proposal operator-job-evidence-body";
    pre.textContent = lines.join("\n");
    details.append(summary, pre);
    meta.appendChild(details);
  }

  function findPersonSidebarButton(personId) {
    return [...document.querySelectorAll("#personList .person-item")]
      .find((button) => button.dataset.personId === personId) || null;
  }

  async function openJobPerson(job) {
    const personId = String(job?.person_id || "").trim();
    if (!personId) return;
    const sidebarButton = findPersonSidebarButton(personId);
    const status = document.getElementById("operatorJobsStatus");
    if (!sidebarButton) {
      if (status) status.textContent = `Person ${personId} findes ikke længere i Person Studio-listen.`;
      return;
    }
    sidebarButton.click();
    for (let attempt = 0; attempt < 40 && currentPersonId() !== personId; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    if (currentPersonId() !== personId) {
      if (status) status.textContent = `Person ${personId} kunne ikke åbnes fra Drift.`;
      return;
    }
    const targetTab = String(job?.kind || "") === "voice-build" ? "voice" : "body";
    document.querySelector(`.tab[data-tab="${targetTab}"]`)?.click();
  }

  function filteredLaunches(launches) {
    const personFilter = document.getElementById("operatorLaunchPersonFilter")?.value || "all";
    const categoryFilter = document.getElementById("operatorLaunchCategoryFilter")?.value || "all";
    const stateFilter = document.getElementById("operatorLaunchStateFilter")?.value || "all";
    const search = (document.getElementById("operatorLaunchSearch")?.value || "").trim().toLowerCase();
    const selectedPerson = currentPersonId();

    return launches.filter((launch) => {
      const context = launch?.context && typeof launch.context === "object" ? launch.context : {};
      if (
        personFilter === "current"
        && (!selectedPerson || String(context.person_id || "") !== selectedPerson)
      ) return false;
      if (categoryFilter !== "all" && String(launch?.category || "") !== categoryFilter) return false;
      if (stateFilter !== "all" && String(launch?.state || "unknown") !== stateFilter) return false;
      if (!search) return true;
      const haystack = [
        launch?.launch_id,
        launch?.category,
        launch?.state,
        launch?.pid,
        launch?.child_pid,
        context.person_id,
        context.gate,
        context.action,
        context.body_revision,
        context.bodyrig_revision,
        context.preview_job_id,
        context.p0_root,
        launch?.integrity_error,
      ].map((value) => String(value || "").toLowerCase()).join("\n");
      return haystack.includes(search);
    });
  }

  function launchEvidenceLines(launch) {
    const context = launch?.context && typeof launch.context === "object" ? launch.context : {};
    const fields = [
      ["Launch id", launch?.launch_id],
      ["Category", launch?.category],
      ["State", launch?.state],
      ["Person", context.person_id],
      ["Gate", context.gate],
      ["Action", context.action],
      ["Body revision", context.body_revision],
      ["BodyRig revision", context.bodyrig_revision],
      ["Preview job id", context.preview_job_id],
      ["P0 root", context.p0_root],
      ["Process role", launch?.process_role],
      ["Supervisor PID", launch?.pid],
      ["PowerShell PID", launch?.child_pid],
      ["Heartbeat", launch?.heartbeat_utc],
      ["Heartbeat age seconds", launch?.heartbeat_age_seconds],
      ["Result recorded", launch?.result_recorded === true ? "ja" : (launch?.result_recorded === false ? "nej" : null)],
      ["Exit code", Number.isInteger(launch?.exit_code) ? launch.exit_code : null],
      ["Started", launch?.started_utc],
      ["Finished", launch?.finished_utc],
      ["Duration seconds", Number.isFinite(launch?.duration_seconds) ? launch.duration_seconds : null],
      ["Integrity valid", launch?.integrity_valid === true ? "ja" : (launch?.integrity_valid === false ? "nej" : null)],
      ["Integrity error", launch?.integrity_error],
      ["Log bytes", Number.isFinite(launch?.log_bytes) ? launch.log_bytes : null],
    ];
    return fields
      .filter(([, value]) => value !== undefined && value !== null && String(value) !== "")
      .map(([label, value]) => `${label}: ${value}`);
  }

  function appendLaunchEvidence(meta, launch) {
    const lines = launchEvidenceLines(launch);
    if (!lines.length) return;
    const details = document.createElement("details");
    details.className = "operator-launch-evidence";
    const summary = document.createElement("summary");
    summary.textContent = "Evidence / detaljer";
    const pre = document.createElement("pre");
    pre.className = "proposal operator-launch-evidence-body";
    pre.textContent = lines.join("\n");
    details.append(summary, pre);
    meta.appendChild(details);
  }

  function appendLaunchLog(meta, launch) {
    if (!launch?.log_tail) return;
    const details = document.createElement("details");
    details.className = "operator-launch-log-wrap";
    const summary = document.createElement("summary");
    summary.textContent = "Seneste operator-log";
    const pre = document.createElement("pre");
    pre.className = "proposal operator-launch-log";
    pre.textContent = String(launch.log_tail);
    details.append(summary, pre);
    meta.appendChild(details);
  }

  async function openLaunchPerson(launch) {
    const context = launch?.context && typeof launch.context === "object" ? launch.context : {};
    const personId = String(context.person_id || "").trim();
    if (!personId) return;
    const sidebarButton = findPersonSidebarButton(personId);
    const status = document.getElementById("operatorLaunchesStatus");
    if (!sidebarButton) {
      if (status) status.textContent = `Person ${personId} findes ikke længere i Person Studio-listen.`;
      return;
    }
    sidebarButton.click();
    for (let attempt = 0; attempt < 40 && currentPersonId() !== personId; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    if (currentPersonId() !== personId) {
      if (status) status.textContent = `Person ${personId} kunne ikke åbnes fra launchhistorikken.`;
      return;
    }
    document.querySelector('.tab[data-tab="body"]')?.click();
  }

  function latestByKey(items, keyOf, stampOf) {
    const latest = new Map();
    for (const item of items) {
      const key = String(keyOf(item) || "");
      if (!key) continue;
      const stamp = String(stampOf(item) || "");
      const current = latest.get(key);
      if (!current || stamp > current.stamp) latest.set(key, { stamp, item });
    }
    return [...latest.values()].map((entry) => entry.item);
  }

  function jobAttention(payload) {
    if (payload?.error) return "Persisted jobs";
    const jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
    const actionRequired = jobs.filter((job) => ACTION_JOB_STATES.has(String(job.status)));
    const monitoringErrors = jobs.filter((job) => Boolean(job?.monitoring_error));
    const latest = latestByKey(
      jobs,
      (job) => `${job.kind || "job"}::${job.person_id || "global"}`,
      (job) => job.created_utc || job.started_utc || job.completed_utc || ""
    );
    const latestFailed = latest.filter((job) => ["failed", "interrupted"].includes(String(job.status)));
    const parts = [];
    if (actionRequired.length) parts.push(`${actionRequired.length} kræver input`);
    if (monitoringErrors.length) parts.push(`${monitoringErrors.length} VoiceRig-syncfejl`);
    if (latestFailed.length) parts.push(`${latestFailed.length} seneste spor fejlet/afbrudt`);
    return parts.length ? `Jobs (${parts.join(", ")})` : null;
  }

  function launchAttention(payload) {
    if (payload?.error) return "Operator-kørsler";
    const launches = Array.isArray(payload?.launches) ? payload.launches : [];
    const latest = latestByKey(
      launches,
      (launch) => {
        const context = launch?.context && typeof launch.context === "object" ? launch.context : {};
        const gate = context.gate || context.action || "";
        return `${launch.category || "operator"}::${gate}`;
      },
      (launch) => launch.started_utc || launch.finished_utc || ""
    );
    const failed = latest.filter((launch) => String(launch.state) === "failed").length;
    const unknown = latest.filter((launch) => String(launch.state) === "unknown").length;
    const parts = [];
    if (failed) parts.push(`${failed} seneste fejl`);
    if (unknown) parts.push(`${unknown} seneste ukendte`);
    return parts.length ? `Operator-kørsler (${parts.join(", ")})` : null;
  }

  async function cancelJob(jobId) {
    if (!jobId) return;
    try {
      await api(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
      await refresh(true);
    } catch (error) {
      const status = document.getElementById("operatorJobsStatus");
      if (status) status.textContent = `Cancel fejlede: ${error.message}`;
    }
  }

  function renderLaunches(payload) {
    lastLaunchesPayload = payload;
    const host = document.getElementById("operatorLaunches");
    const status = document.getElementById("operatorLaunchesStatus");
    if (!host || !status) return;
    host.replaceChildren();
    if (payload?.error) {
      status.textContent = `Kunne ikke hente operator-kørsler: ${payload.error}`;
      const error = document.createElement("div");
      error.className = "muted-text";
      error.textContent = "Operator-launch feed er utilgængeligt; PASS/FEJL kan ikke overvåges fra Drift lige nu.";
      host.appendChild(error);
      return;
    }
    const launches = Array.isArray(payload?.launches) ? payload.launches : [];
    const running = launches.filter((item) => item.state === "running");
    const succeeded = launches.filter((item) => item.state === "succeeded");
    const failed = launches.filter((item) => item.state === "failed");
    const unknown = launches.filter((item) => item.state === "unknown");
    const filtered = filteredLaunches(launches);
    const visibleLaunches = filtered.slice(0, 30);
    status.textContent = `${visibleLaunches.length}/${filtered.length} viste · ${running.length} aktive · ${succeeded.length} PASS · ${failed.length} fejl · ${unknown.length} ukendte · ${launches.length} hentet`;
    if (!visibleLaunches.length) {
      const empty = document.createElement("div");
      empty.className = "muted-text";
      empty.textContent = launches.length ? "Ingen operator-kørsler matcher de valgte filtre." : "Ingen UI-startede operator-kørsler endnu.";
      host.appendChild(empty);
      return;
    }
    for (const launch of visibleLaunches) {
      const row = document.createElement("div");
      row.className = "operator-job-row";
      const meta = document.createElement("div");
      meta.className = "operator-launch-meta";
      const title = document.createElement("strong");
      title.textContent = launch.launch_id || "ukendt launch";
      const detail = document.createElement("div");
      detail.className = "fine-print";
      const gate = launch.context?.gate || launch.context?.action || "";
      detail.textContent = [
        launch.category || "operator",
        gate,
        launch.pid ? `${launch.process_role === "restart-safe-supervisor" ? "Supervisor PID" : "PID"} ${launch.pid}` : "",
        launch.child_pid ? `PowerShell PID ${launch.child_pid}` : "",
        launch.process_role === "restart-safe-supervisor"
          ? (launch.heartbeat_fresh
              ? `heartbeat ${Number.isFinite(launch.heartbeat_age_seconds) ? launch.heartbeat_age_seconds.toFixed(1) + " s" : "frisk"}`
              : "heartbeat mangler/stale")
          : "",
        launch.started_utc || "",
        launch.finished_utc ? `slut ${launch.finished_utc}` : "",
        Number.isFinite(launch.duration_seconds) ? `${launch.duration_seconds.toFixed(1)} s` : "",
        Number.isInteger(launch.exit_code) ? `exit ${launch.exit_code}` : "",
        launch.integrity_valid === false ? "INTEGRITETSFEJL" : "",
      ].filter(Boolean).join(" · ");
      meta.append(title, detail);
      if (launch.integrity_valid === false && launch.integrity_error) {
        const integrity = document.createElement("div");
        integrity.className = "operator-job-error";
        integrity.textContent = `Launch receipt afvist: ${launch.integrity_error}`;
        meta.appendChild(integrity);
      }
      appendLaunchEvidence(meta, launch);
      appendLaunchLog(meta, launch);

      const controls = document.createElement("div");
      controls.className = "operator-job-controls";
      const badge = document.createElement("span");
      const state = String(launch.state || "unknown");
      badge.className = `badge${state === "unknown" ? " muted" : ""}`;
      badge.textContent =
        state === "running" ? "Kører" :
        state === "succeeded" ? "PASS" :
        state === "failed" ? "FEJL" :
        "Afsluttet/ukendt";
      controls.appendChild(badge);

      const personId = String(launch?.context?.person_id || "").trim();
      if (personId) {
        const openPerson = document.createElement("button");
        openPerson.type = "button";
        openPerson.className = "secondary";
        openPerson.textContent = "Åbn Krop";
        openPerson.addEventListener("click", () => void openLaunchPerson(launch));
        controls.appendChild(openPerson);
      }

      row.append(meta, controls);
      host.appendChild(row);
    }
  }

  function renderJobs(payload) {
    lastJobsPayload = payload;
    const host = document.getElementById("operatorJobs");
    const status = document.getElementById("operatorJobsStatus");
    if (!host || !status) return;
    host.replaceChildren();
    if (payload?.error) {
      status.textContent = `Kunne ikke hente persisted jobs: ${payload.error}`;
      const error = document.createElement("div");
      error.className = "muted-text";
      error.textContent = "Job-feed er utilgængeligt; Drift kan ikke bekræfte jobstatus lige nu.";
      host.appendChild(error);
      return;
    }

    const jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
    const open = jobs.filter((job) => OPEN_JOB_STATES.has(String(job.status)));
    const actionRequired = jobs.filter((job) => ACTION_JOB_STATES.has(String(job.status)));
    const failed = jobs.filter((job) => ["failed", "interrupted"].includes(String(job.status)));
    const monitoringErrors = jobs.filter((job) => Boolean(job?.monitoring_error));
    const filtered = filteredJobs(jobs);
    const recent = filtered.slice().sort((a, b) =>
      String(b.completed_utc || b.started_utc || b.created_utc || "").localeCompare(
        String(a.completed_utc || a.started_utc || a.created_utc || "")
      )
    ).slice(0, 30);
    status.textContent = `${recent.length}/${filtered.length} viste · ${open.length} aktive · ${actionRequired.length} kræver input · ${monitoringErrors.length} VoiceRig-syncfejl · ${failed.length} fejlet/afbrudt · ${jobs.length} persisted jobs`;

    if (!recent.length) {
      const empty = document.createElement("div");
      empty.className = "muted-text";
      empty.textContent = jobs.length ? "Ingen jobs matcher de valgte filtre." : "Ingen jobs endnu.";
      host.appendChild(empty);
      return;
    }

    for (const job of recent) {
      const row = document.createElement("div");
      row.className = "operator-job-row operator-job-row-detailed";

      const meta = document.createElement("div");
      meta.className = "operator-job-meta";
      const title = document.createElement("strong");
      title.textContent = job.job_id || "ukendt job";

      const detail = document.createElement("div");
      detail.className = "fine-print";
      detail.textContent = [
        jobLabel(job),
        job.pid ? `PID ${job.pid}` : "",
        job.created_utc ? `oprettet ${job.created_utc}` : "",
        job.started_utc ? `start ${job.started_utc}` : "",
        job.completed_utc ? `slut ${job.completed_utc}` : "",
      ].filter(Boolean).join(" · ");
      meta.append(title, detail);

      const numericProgress = typeof job.progress === "number" && Number.isFinite(job.progress)
        ? job.progress
        : null;
      if (numericProgress !== null) {
        const progress = document.createElement("progress");
        progress.className = "operator-job-progress";
        progress.max = 100;
        progress.value = Math.max(0, Math.min(100, numericProgress));
        progress.title = job.progress_kind === "pipeline-phase-estimate-v1"
          ? "Evidence-backed faseestimat; ikke et tidsestimat."
          : "Rapporteret jobprogress.";
        meta.appendChild(progress);
        const progressText = document.createElement("div");
        progressText.className = "fine-print";
        progressText.textContent = `${Math.round(progress.value)}% · ${job.stage || job.resume_stage || "ukendt stage"}`;
        meta.appendChild(progressText);
      }

      if (job.message) {
        const message = document.createElement("div");
        message.className = "operator-job-message";
        message.textContent = String(job.message);
        meta.appendChild(message);
      }
      if (job.error) {
        const error = document.createElement("div");
        error.className = "operator-job-error";
        error.textContent = `Fejl: ${job.error}`;
        meta.appendChild(error);
      }
      if (job.monitoring_error) {
        const monitoringError = document.createElement("div");
        monitoringError.className = "operator-job-error";
        monitoringError.textContent = String(job.monitoring_error);
        meta.appendChild(monitoringError);
      }
      renderVoiceJobChoices(meta, job);
      if (job.diagnostic_tail) {
        const diagnostic = document.createElement("pre");
        diagnostic.className = "proposal operator-job-diagnostic";
        diagnostic.textContent = String(job.diagnostic_tail);
        meta.appendChild(diagnostic);
      }
      appendJobEvidence(meta, job);

      const controls = document.createElement("div");
      controls.className = "operator-job-controls";
      const statusBadge = document.createElement("span");
      const currentStatus = String(job.status || "");
      statusBadge.className = `badge${OPEN_JOB_STATES.has(currentStatus) && !ACTION_JOB_STATES.has(currentStatus) ? "" : " muted"}`;
      statusBadge.textContent = ACTION_JOB_STATES.has(currentStatus)
        ? `INPUT · ${jobStatusLabel(currentStatus)}`
        : jobStatusLabel(currentStatus);
      controls.appendChild(statusBadge);

      if (job.person_id) {
        const openPerson = document.createElement("button");
        openPerson.type = "button";
        openPerson.className = "secondary";
        openPerson.textContent = String(job.kind || "") === "voice-build" ? "Åbn Stemme" : "Åbn Krop";
        openPerson.addEventListener("click", () => void openJobPerson(job));
        controls.appendChild(openPerson);
      }

      if (jobCanCancel(job)) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = "Annullér";
        button.addEventListener("click", () => void cancelJob(job.job_id));
        controls.appendChild(button);
      } else if (String(job.kind || "") === "body-build" && currentStatus === "running") {
        const safety = document.createElement("div");
        safety.className = "fine-print";
        safety.textContent = "Fysisk build kan ikke annulleres sikkert midt i WSL/child-processen.";
        controls.appendChild(safety);
      }

      row.append(meta, controls);
      host.appendChild(row);
    }
  }

  async function refresh(force = false) {
    if (!panel()) return;
    if (!visible() && !force) return;
    const current = ++serial;
    const summary = document.getElementById("operatorSummary");
    if (summary) summary.textContent = "Kontrollerer BodyRig-systemet…";
    markServicesChecking();

    const serviceResults = await Promise.all(
      SERVICES.map(async ([key, label, url]) => {
        try {
          const read = await readApi(url);
          return recordServiceObservation(key, { key, label, ok: true, ...read });
        } catch (error) {
          return recordServiceObservation(key, {
            key,
            label,
            ok: false,
            error: error.message,
            observed_ms: Date.now(),
          });
        }
      })
    );
    let jobs;
    try {
      jobs = await hydrateOpenVoiceJobs((await readApi("/api/v1/jobs")).value);
    } catch (error) {
      jobs = { jobs: [], error: error.message };
    }
    let launches;
    try {
      launches = (await readApi("/api/v1/operator/launches?limit=50")).value;
    } catch (error) {
      launches = { launches: [], error: error.message };
    }
    let photoreal;
    let digitalTwin;
    const personId = currentPersonId();
    if (!personId) {
      photoreal = { ok: true, value: { state: "no-run", performer: { name: "Ingen person valgt" }, exavatar: { busy: false, phase: "not-started" } } };
      digitalTwin = {
        ok: true,
        value: {
          state: "no-person",
          digital_twin_ready: false,
          production_activation: false,
          milestones: {},
          message: "Ingen person valgt.",
        },
      };
    } else {
      try {
        const profile = (await readApi(`/api/v1/people/${encodeURIComponent(personId)}`)).value;
        const source = profile?.source && typeof profile.source === "object" ? profile.source : {};
        if (source.kind !== "stash-performer" || !String(source.performer_id || "").trim()) {
          photoreal = {
            ok: true,
            value: {
              state: "no-run",
              performer: { name: profile?.name || personId },
              exavatar: { busy: false, phase: "not-applicable" },
              monitoring_note: "Personen er ikke bundet til en Stash performer.",
            },
          };
        } else {
          photoreal = {
            ok: true,
            value: (await readApi(
              `/api/v1/people/${encodeURIComponent(personId)}/body/photoreal-control-plane`,
              10000
            )).value,
          };
        }
      } catch (error) {
        photoreal = { ok: false, error: error.message };
      }
      try {
        digitalTwin = {
          ok: true,
          value: (await readApi(
            `/api/v1/people/${encodeURIComponent(personId)}/digital-twin-readiness`,
            10000
          )).value,
        };
      } catch (error) {
        digitalTwin = { ok: false, error: error.message };
      }
    }
    if (current !== serial) return;

    for (const result of serviceResults) renderService(result.key, result.label, result);
    renderJobs(jobs);
    renderLaunches(launches);
    renderPhotoreal(photoreal);
    renderDigitalTwin(digitalTwin);
    const attention = serviceResults
      .filter((item) =>
        item.ok === false
        || !serviceResultFresh(item)
        || !serviceHealthy(item.key, item.value)
      )
      .map((item) => item.label);
    const jobsAttention = jobAttention(jobs);
    const launchesAttention = launchAttention(launches);
    const photorealAttentionValue = photoreal?.ok === false
      ? "Photoreal / ExAvatar"
      : photorealAttention(photoreal?.value);
    const digitalTwinAttentionValue = digitalTwinAttention(digitalTwin);
    if (jobsAttention) attention.push(jobsAttention);
    if (launchesAttention) attention.push(launchesAttention);
    if (photorealAttentionValue) attention.push(photorealAttentionValue);
    if (digitalTwinAttentionValue) attention.push(digitalTwinAttentionValue);
    if (summary) {
      summary.textContent = attention.length
        ? `${attention.length} områder kræver opmærksomhed: ${attention.join(", ")}.`
        : "BodyRig, integrations-health, runtime, jobs og operator authority er grønne.";
    }
    schedule(visible() ? 10000 : 30000);
  }

  function schedule(delay) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void refresh(false), delay);
  }

  const personNode = document.getElementById("personId");
  if (personNode) {
    new MutationObserver(() => {
      if (visible()) void refresh(true);
    }).observe(personNode, { childList: true, characterData: true, subtree: true });
  }

  for (const id of ["operatorLaunchPersonFilter", "operatorLaunchCategoryFilter", "operatorLaunchStateFilter"]) {
    document.getElementById(id)?.addEventListener("change", () => {
      if (lastLaunchesPayload) renderLaunches(lastLaunchesPayload);
    });
  }
  document.getElementById("operatorLaunchSearch")?.addEventListener("input", () => {
    if (lastLaunchesPayload) renderLaunches(lastLaunchesPayload);
  });

  for (const id of ["operatorJobPersonFilter", "operatorJobKindFilter", "operatorJobStateFilter"]) {
    document.getElementById(id)?.addEventListener("change", () => {
      if (lastJobsPayload) renderJobs(lastJobsPayload);
    });
  }
  document.getElementById("operatorJobSearch")?.addEventListener("input", () => {
    if (lastJobsPayload) renderJobs(lastJobsPayload);
  });

  document.getElementById("operatorRefresh")?.addEventListener("click", () => void refresh(true));
  document.querySelector('.tab[data-tab="operations"]')?.addEventListener("click", () => {
    setTimeout(() => void refresh(true), 0);
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && visible()) void refresh(true);
  });
  restoreServiceObservations();
  schedule(1500);
})();
