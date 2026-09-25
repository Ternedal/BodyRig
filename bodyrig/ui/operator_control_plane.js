(() => {
  let timer = null;
  let serial = 0;

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

  function renderPhotoreal(result) {
    const summary = document.getElementById("operator-photoreal-summary");
    const detail = document.getElementById("operator-photoreal-detail");
    if (!summary || !detail) return;
    if (result?.ok === false) {
      summary.textContent = result.error || "Photoreal-status kunne ikke læses.";
      detail.textContent = "Fail-closed: Drift kan ikke bekræfte den valgte persons Photoreal/ExAvatar-status.";
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

  function setBadge(id, ok, text) {
    const badge = document.getElementById(id);
    if (!badge) return;
    badge.textContent = text;
    badge.classList.toggle("muted", !ok);
  }

  function serviceSummary(key, value) {
    if (key === "bodyrig") {
      const build = value.physical_build_ready === true
        ? "physical build klar"
        : `physical build blokeret${value.physical_build_reason ? `: ${value.physical_build_reason}` : ""}`;
      return `v${value.version || "?"} · ${value.people ?? "?"} personer · ${build}`;
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
    if (!value || typeof value !== "object") return false;
    if (key === "operator") return value.ok === true;
    if (key === "bodyrig") return value.ok === true && value.physical_build_ready === true;
    if (key === "stash") return value.ok === true && value.performer_read === true;
    if (key === "modelrig" || key === "voicerig") return value.ok === true;
    if (key === "system") return value.wsl_cuda?.ready === true && value.powershell_7 === true;
    if (key === "runtime") return true;
    return value.ok !== false;
  }

  function renderService(key, label, result) {
    const summary = document.getElementById(`operator-${key}-summary`);
    const badgeId = `operator-${key}-badge`;
    if (!summary) return;
    if (result.ok === false && result.error) {
      summary.textContent = result.error;
      setBadge(badgeId, false, "Offline");
      return;
    }
    const value = result.value || {};
    const healthy = serviceHealthy(key, value);
    summary.textContent = serviceSummary(key, value);
    setBadge(badgeId, healthy, healthy ? "Klar" : "Blokeret");
    if (key === "system") {
      renderSystemDetail(value);
      renderSystemActions(value);
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
    const latest = latestByKey(
      jobs,
      (job) => `${job.kind || "job"}::${job.person_id || "global"}`,
      (job) => job.created_utc || job.started_utc || job.completed_utc || ""
    );
    const latestFailed = latest.filter((job) => ["failed", "interrupted"].includes(String(job.status)));
    const parts = [];
    if (actionRequired.length) parts.push(`${actionRequired.length} kræver input`);
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
    status.textContent = `${running.length} aktive · ${succeeded.length} PASS · ${failed.length} fejl · ${unknown.length} ukendte · ${launches.length} viste`;
    if (!launches.length) {
      const empty = document.createElement("div");
      empty.className = "muted-text";
      empty.textContent = "Ingen UI-startede operator-kørsler endnu.";
      host.appendChild(empty);
      return;
    }
    for (const launch of launches) {
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
      ].filter(Boolean).join(" · ");
      meta.append(title, detail);
      if (launch.log_tail) {
        const log = document.createElement("pre");
        log.className = "proposal operator-launch-log";
        log.textContent = launch.log_tail;
        meta.appendChild(log);
      }
      const badge = document.createElement("span");
      const state = String(launch.state || "unknown");
      badge.className = `badge${state === "unknown" ? " muted" : ""}`;
      badge.textContent =
        state === "running" ? "Kører" :
        state === "succeeded" ? "PASS" :
        state === "failed" ? "FEJL" :
        "Afsluttet/ukendt";
      row.append(meta, badge);
      host.appendChild(row);
    }
  }

  function renderJobs(payload) {
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
    const recent = jobs.slice().sort((a, b) =>
      String(b.completed_utc || b.started_utc || b.created_utc || "").localeCompare(
        String(a.completed_utc || a.started_utc || a.created_utc || "")
      )
    ).slice(0, 12);
    status.textContent = `${open.length} aktive · ${actionRequired.length} kræver input · ${failed.length} fejlet/afbrudt · ${jobs.length} persisted jobs`;

    if (!recent.length) {
      const empty = document.createElement("div");
      empty.className = "muted-text";
      empty.textContent = "Ingen jobs endnu.";
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
      if (job.diagnostic_tail) {
        const diagnostic = document.createElement("pre");
        diagnostic.className = "proposal operator-job-diagnostic";
        diagnostic.textContent = String(job.diagnostic_tail);
        meta.appendChild(diagnostic);
      }

      const controls = document.createElement("div");
      controls.className = "operator-job-controls";
      const statusBadge = document.createElement("span");
      const currentStatus = String(job.status || "");
      statusBadge.className = `badge${OPEN_JOB_STATES.has(currentStatus) && !ACTION_JOB_STATES.has(currentStatus) ? "" : " muted"}`;
      statusBadge.textContent = ACTION_JOB_STATES.has(currentStatus)
        ? `INPUT · ${jobStatusLabel(currentStatus)}`
        : jobStatusLabel(currentStatus);
      controls.appendChild(statusBadge);

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

    const serviceResults = await Promise.all(
      SERVICES.map(async ([key, label, url]) => {
        try {
          return { key, label, ok: true, value: await api(url) };
        } catch (error) {
          return { key, label, ok: false, error: error.message };
        }
      })
    );
    let jobs;
    try {
      jobs = await api("/api/v1/jobs");
    } catch (error) {
      jobs = { jobs: [], error: error.message };
    }
    let launches;
    try {
      launches = await api("/api/v1/operator/launches?limit=12");
    } catch (error) {
      launches = { launches: [], error: error.message };
    }
    let photoreal;
    const personId = currentPersonId();
    if (!personId) {
      photoreal = { ok: true, value: { state: "no-run", performer: { name: "Ingen person valgt" }, exavatar: { busy: false, phase: "not-started" } } };
    } else {
      try {
        const profile = await api(`/api/v1/people/${encodeURIComponent(personId)}`);
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
            value: await api(`/api/v1/people/${encodeURIComponent(personId)}/body/photoreal-control-plane`),
          };
        }
      } catch (error) {
        photoreal = { ok: false, error: error.message };
      }
    }
    if (current !== serial) return;

    for (const result of serviceResults) renderService(result.key, result.label, result);
    renderJobs(jobs);
    renderLaunches(launches);
    renderPhotoreal(photoreal);
    const attention = serviceResults
      .filter((item) => item.ok === false || !serviceHealthy(item.key, item.value))
      .map((item) => item.label);
    const jobsAttention = jobAttention(jobs);
    const launchesAttention = launchAttention(launches);
    const photorealAttentionValue = photoreal?.ok === false
      ? "Photoreal / ExAvatar"
      : photorealAttention(photoreal?.value);
    if (jobsAttention) attention.push(jobsAttention);
    if (launchesAttention) attention.push(launchesAttention);
    if (photorealAttentionValue) attention.push(photorealAttentionValue);
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

  document.getElementById("operatorRefresh")?.addEventListener("click", () => void refresh(true));
  document.querySelector('.tab[data-tab="operations"]')?.addEventListener("click", () => {
    setTimeout(() => void refresh(true), 0);
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && visible()) void refresh(true);
  });
  schedule(1500);
})();
