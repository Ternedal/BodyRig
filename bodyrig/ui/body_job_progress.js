(() => {
  const ACTIVE = new Set(["queued", "running"]);
  const FAILURE = new Set(["failed", "canceled", "interrupted"]);
  let timer = null;
  let lastPersonId = "";

  function personId() {
    return (document.getElementById("personId")?.textContent || "").trim();
  }

  function formatDuration(seconds) {
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = value % 60;
    if (hours > 0) return `${hours} t ${minutes} min`;
    if (minutes > 0) return `${minutes} min ${secs} sek`;
    return `${secs} sek`;
  }

  function stripAnsi(value) {
    return String(value || "").replace(/\x1B(?:[@-_][0-?]*[ -/]*[@-~]|\[[0-?]*[ -/]*[@-~])/g, "");
  }

  function concreteFailure(job) {
    const tail = stripAnsi(job?.diagnostic_tail || "");
    let candidate = "";
    for (const rawLine of tail.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line) continue;
      const failIndex = line.lastIndexOf("FAIL:");
      if (failIndex >= 0) candidate = line.slice(failIndex + 5).trim();
    }
    if (!candidate) return "";
    candidate = candidate.replace(/\s*\|\s*staging retained:.*$/i, "").trim();
    return candidate.slice(0, 1600);
  }

  function replacePersistedError(job, summary) {
    if (!summary || !FAILURE.has(job?.status)) return;
    const detail = document.getElementById("bodyJobDetail");
    if (!detail) return;
    const lines = String(detail.textContent || "").split("\n");
    const index = lines.findIndex((line) => line.startsWith("Fejl:"));
    const value = `Fejl: ${summary}`;
    if (index >= 0) lines[index] = value;
    else lines.push(value);
    detail.textContent = lines.join("\n");
  }

  function displayPhase(job) {
    // Backend v1 groups recovery, identity capture and SiTH fitting under one
    // evidence phase. Do not pretend that observation evidence means SiTH has
    // already started: PHALP/4D-Humans recovery may still be processing the
    // selected segments at this point.
    if (job?.stage === "high_fidelity_reconstruction") {
      return "Recovery/identity/high-fidelity pipeline kører. Lange PHALP/4D-Humans segmenter kan ligge i denne fase uden nye linjer i hovedloggen.";
    }
    return String(job?.message || job?.stage || job?.status || "ukendt fase");
  }

  function ensurePanel() {
    const card = document.getElementById("bodyJobCard");
    if (!card) return null;
    let panel = document.getElementById("bodyJobProgressPanel");
    if (panel) return panel;

    panel = document.createElement("div");
    panel.id = "bodyJobProgressPanel";
    panel.className = "space-top";
    panel.hidden = true;
    panel.innerHTML = `
      <progress id="bodyJobProgressBar" max="100" value="0" style="width:100%"></progress>
      <div id="bodyJobProgressText" class="fine-print"></div>
      <pre id="bodyJobDiagnosticTail" class="proposal hidden" style="white-space:pre-wrap;max-height:18rem;overflow:auto"></pre>`;

    const detail = document.getElementById("bodyJobDetail");
    if (detail?.parentNode === card) detail.insertAdjacentElement("afterend", panel);
    else card.appendChild(panel);
    return panel;
  }

  function render(job) {
    const panel = ensurePanel();
    if (!panel) return;
    const bar = document.getElementById("bodyJobProgressBar");
    const text = document.getElementById("bodyJobProgressText");
    const diagnostic = document.getElementById("bodyJobDiagnosticTail");
    if (!bar || !text || !diagnostic) return;

    if (!job) {
      panel.hidden = true;
      return;
    }

    panel.hidden = false;
    const reported = Number(job.progress);
    const progress = Number.isFinite(reported) ? Math.max(0, Math.min(100, reported)) : 0;
    bar.value = job.status === "succeeded" ? 100 : progress;

    const elapsed = formatDuration(job.elapsed_seconds);
    const phase = displayPhase(job);
    const failure = concreteFailure(job);
    if (job.status === "succeeded") {
      text.textContent = `Færdig · 100% · samlet køretid ${elapsed}`;
    } else if (ACTIVE.has(job.status)) {
      const estimate = job.progress_kind === "pipeline-phase-estimate-v1" ? "faseestimat" : "progress";
      text.textContent = `${phase} · ca. ${Math.round(progress)}% ${estimate} · kørt ${elapsed}. Procenten følger pipeline-evidence, ikke en opdigtet ETA.`;
    } else if (failure) {
      text.textContent = `Stoppet efter ${elapsed} · ${failure}`;
    } else {
      text.textContent = `${phase} · stoppet efter ${elapsed}`;
    }

    const tail = String(job.diagnostic_tail || "").trim();
    if (FAILURE.has(job.status) && tail) {
      diagnostic.textContent = stripAnsi(tail);
      diagnostic.classList.remove("hidden");
    } else {
      diagnostic.textContent = "";
      diagnostic.classList.add("hidden");
    }
    replacePersistedError(job, failure);
  }

  async function refresh() {
    clearTimeout(timer);
    const id = personId();
    if (!id) {
      render(null);
      timer = setTimeout(refresh, 2500);
      return;
    }
    lastPersonId = id;
    try {
      const response = await fetch(`/api/v1/jobs?person_id=${encodeURIComponent(id)}`, {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      if (personId() !== id) return void schedule(0);
      const job = Array.isArray(payload.jobs)
        ? payload.jobs.find((item) => item?.kind === "body-build") || null
        : null;
      render(job);
      schedule(job && ACTIVE.has(job.status) ? 2000 : 5000);
    } catch {
      schedule(5000);
    }
  }

  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(() => void refresh(), delay);
  }

  const personNode = document.getElementById("personId");
  if (personNode) {
    new MutationObserver(() => {
      const current = personId();
      if (current !== lastPersonId) schedule(0);
    }).observe(personNode, { childList: true, characterData: true, subtree: true });
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) schedule(0);
  });
  window.addEventListener("DOMContentLoaded", () => schedule(0), { once: true });
})();
