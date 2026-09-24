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

  function panel() {
    return document.getElementById("tab-operations");
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
      return `WSL/CUDA ${wsl.ready === true ? "klar" : "blokeret"} · CUDA ${cuda} · ${gpu} · Quest ${quest.quest_device_count ?? 0}`;
    }
    return JSON.stringify(value);
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
    const healthy =
      key === "operator" ? value.ok === true :
      key === "bodyrig" ? value.ok === true :
      key === "stash" ? value.ok === true :
      key === "system" ? (value.wsl_cuda?.ready === true && value.powershell_7 === true) :
      true;
    summary.textContent = serviceSummary(key, value);
    setBadge(badgeId, healthy, healthy ? "Klar" : "Blokeret");
  }

  function jobLabel(job) {
    const kind = String(job.kind || "job");
    const person = String(job.person_id || "");
    const stage = String(job.stage || job.resume_stage || "");
    return [kind, person, stage].filter(Boolean).join(" · ");
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

  function renderJobs(payload) {
    const host = document.getElementById("operatorJobs");
    const status = document.getElementById("operatorJobsStatus");
    if (!host || !status) return;
    host.replaceChildren();
    const jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
    const open = jobs.filter((job) => ["queued", "running"].includes(String(job.status)));
    const recent = jobs.slice().sort((a, b) =>
      String(b.updated_utc || b.created_utc || "").localeCompare(String(a.updated_utc || a.created_utc || ""))
    ).slice(0, 12);
    status.textContent = `${open.length} aktive · ${jobs.length} persisted jobs`;
    if (!recent.length) {
      const empty = document.createElement("div");
      empty.className = "muted-text";
      empty.textContent = "Ingen jobs endnu.";
      host.appendChild(empty);
      return;
    }
    for (const job of recent) {
      const row = document.createElement("div");
      row.className = "operator-job-row";
      const meta = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = job.job_id || "ukendt job";
      const detail = document.createElement("div");
      detail.className = "fine-print";
      detail.textContent = `${jobLabel(job)} · ${job.status || "ukendt"}`;
      meta.append(title, detail);
      row.appendChild(meta);
      if (["queued", "running"].includes(String(job.status))) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary";
        button.textContent = "Annullér";
        button.addEventListener("click", () => void cancelJob(job.job_id));
        row.appendChild(button);
      } else {
        const badge = document.createElement("span");
        badge.className = "badge muted";
        badge.textContent = job.status || "ukendt";
        row.appendChild(badge);
      }
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
    if (current !== serial) return;

    for (const result of serviceResults) renderService(result.key, result.label, result);
    renderJobs(jobs);
    const failures = serviceResults.filter((item) => item.ok === false || (
      item.key === "operator" && item.value?.ok !== true
    ));
    if (summary) {
      summary.textContent = failures.length
        ? `${failures.length} systemområder kræver opmærksomhed.`
        : "BodyRig, integrations-health og operator authority er læst uden fejl.";
    }
    schedule(visible() ? 10000 : 30000);
  }

  function schedule(delay) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void refresh(false), delay);
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
